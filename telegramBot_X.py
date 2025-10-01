# broke_task_bot_v23.py
import logging
import requests
import os
from pymongo import MongoClient
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from dotenv import load_dotenv
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.transaction import Transaction
from solders.system_program import transfer, TransferParams

# ---------------- LOAD ENV ----------------
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN")
ADMIN_PRIVATE_KEY = eval(os.getenv("ADMIN_PRIVATE_KEY"))  # loads as list of ints
BOT_WALLET = os.getenv("BOT_WALLET")
GROUP_ID = int(os.getenv("GROUP_ID"))
ADMINS = [int(x) for x in os.getenv("ADMINS").split(",")]
MONGO_URI = os.getenv("MONGO_URI")

# -----------Connect to Solana Devnet----------------
solana_client = Client("https://api.devnet.solana.com")

def send_reward(admin_private_key_list, to_wallet_str, amount_sol):
    """
    Send SOL from admin wallet to user's wallet using solders.
    """
    try:
        # Load admin wallet
        sender = Keypair.from_bytes(bytes(admin_private_key_list))

        # Receiver wallet
        receiver = Pubkey.from_string(to_wallet_str)

        # Create transfer instruction
        tx_instruction = transfer(
            TransferParams(
                from_pubkey=sender.pubkey(),
                to_pubkey=receiver,
                lamports=int(amount_sol * 1_000_000_000)  # Convert SOL → lamports
            )
        )

        # Build & sign transaction
        blockhash = solana_client.get_latest_blockhash().value.blockhash
        txn = Transaction.new_signed_with_payer(
            [tx_instruction],        # instructions
            sender.pubkey(),         # payer
            [sender],                # signers
            blockhash                # recent blockhash
        )

        # Send transaction
        response = solana_client.send_transaction(txn)

        print("✅ Transaction submitted!")
        print("Explorer link: https://explorer.solana.com/tx/" + str(response.value) + "?cluster=devnet")

        return response
    except Exception as e:
        return {"error": str(e)}
    
# ---------------- LOGGING ----------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------------- MONGO DB ----------------
client = MongoClient(MONGO_URI)
db = client['broke_bot']
users_col = db['users']
tasks_col = db['tasks']
claims_col = db['claims']

# ---------------- HELPER FUNCTION ----------------
def get_next_task_id():
    """Get the next task ID from MongoDB to allow multiple tasks."""
    last_task = tasks_col.find_one(sort=[("task_id", -1)])
    if last_task:
        return last_task["task_id"] + 1
    else:
        return 1

# ---------------- VERIFICATION FUNCTIONS ----------------
def verify_x_comment(tweet_id, username):
    url = f"https://api.twitter.com/2/tweets/search/recent?query=conversation_id:{tweet_id}%20from:{username}"
    headers = {"Authorization": f"Bearer {X_BEARER_TOKEN}"}
    logger.info(f"🔎 Checking comment for tweet_id={tweet_id}, username={username}")
    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        logger.error(f"❌ Comment API failed. Status {response.status_code}, Response: {response.text}")
        return False

    data = response.json()
    logger.debug(f"Comment API Response: {data}")

    if "data" in data:
        for tweet in data["data"]:
            if "$Broke" in tweet["text"]:
                logger.info("✅ Comment verification passed")
                return True
        logger.warning("❌ No matching comment with '$Broke'")
    else:
        logger.warning("❌ No comments found in API response")

    return False

def verify_x_retweet(tweet_id, username):
    url = f"https://api.twitter.com/2/tweets/{tweet_id}/retweeted_by"
    headers = {"Authorization": f"Bearer {X_BEARER_TOKEN}"}
    logger.info(f"🔎 Checking retweet for tweet_id={tweet_id}, username={username}")
    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        logger.error(f"❌ Retweet API failed. Status {response.status_code}, Response: {response.text}")
        return False

    data = response.json()
    logger.debug(f"Retweet API Response: {data}")

    for user in data.get('data', []):
        if user.get("username") == username:
            logger.info("✅ Retweet verification passed")
            return True

    logger.warning("❌ Retweet not found for user")
    return False

# ---------------- TELEGRAM BOT HANDLERS ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome! Use /register to register your X username and wallet."
    )

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send your X username and wallet address in this format:\nusername,wallet_address"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.message.from_user.id
    text = update.message.text.strip()
    try:
        x_username, wallet = text.split(",")
        users_col.update_one(
            {"telegram_id": telegram_id},
            {"$set": {"x_username": x_username.strip(), "wallet": wallet.strip()}},
            upsert=True
        )
        logger.info(f"✅ Registered user {telegram_id} with X={x_username.strip()}, wallet={wallet.strip()}")
        await update.message.reply_text(f"✅ Registered X username: {x_username.strip()} and wallet: {wallet.strip()}")
    except Exception as e:
        logger.error(f"❌ Registration failed for {telegram_id}, error: {e}")
        await update.message.reply_text(f"❌ Format incorrect. Use: username,wallet_address\nError: {str(e)}")

# ---------------- ADMIN ADD TASK (PRIVATE CHAT) ----------------
async def add_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.message.from_user.id

    if telegram_id not in ADMINS:
        logger.warning(f"❌ Unauthorized add_task attempt by {telegram_id}")
        await update.message.reply_text("❌ You are not authorized to add tasks.")
        return

    if len(context.args) < 2:
        await update.message.reply_text("Usage: /add_task <tweet_url> <reward>")
        return

    tweet_url = context.args[0]
    reward = float(context.args[1])

    task_id = get_next_task_id()

    task = {"task_id": task_id, "url": tweet_url, "reward": reward}
    tasks_col.insert_one(task)
    claims_col.insert_one({"task_id": task_id, "telegram_ids": []})

    logger.info(f"✅ Task #{task_id} added by admin {telegram_id}, URL={tweet_url}, Reward={reward}")

    # Post task in the group
    keyboard = [
        [InlineKeyboardButton("Go to Post", url=tweet_url),
         InlineKeyboardButton("Verify", callback_data=f"verify|{task_id}|0")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message_text = (
    f"**📌 New Task #{task_id}!**\n\n"
    f"**Comment $Broke on this post and Retweet this post.**\n\n"
    f"💰 Reward: {reward} Broke Coin\n"
    f"🔗 Tweet: {tweet_url}"
)
    await context.bot.send_message(
        chat_id=GROUP_ID,
        text=message_text,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

    await update.message.reply_text(f"✅ Task #{task_id} added and posted in the group.")

# ---------------- HANDLE BUTTON CLICKS ----------------
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split("|")
    
    if data[0] == "verify":
        task_id = int(data[1])
        telegram_id = query.from_user.id
        user = users_col.find_one({"telegram_id": telegram_id})
        
        if not user:
            logger.warning(f"❌ Unregistered user {telegram_id} tried to verify Task #{task_id}")
            await query.message.reply_text("❌ You are not registered. Use /register first.")
            return

        claim = claims_col.find_one({"task_id": task_id})
        if telegram_id in claim["telegram_ids"]:
            logger.warning(f"⚠️ User {telegram_id} tried to re-claim Task #{task_id}")
            await query.message.reply_text("❌ You already claimed this task.")
            return

        tweet_id = tasks_col.find_one({"task_id": task_id})["url"].split("/")[-1]
        username = user["x_username"]
        logger.info(f"🔎 Verifying Task #{task_id} for user {telegram_id}, X={username}")

        comment_ok = verify_x_comment(tweet_id, username)
        retweet_ok = verify_x_retweet(tweet_id, username)

        if comment_ok and retweet_ok:
            claims_col.update_one(
                {"task_id": task_id},
                {"$push": {"telegram_ids": telegram_id}}
            )
            reward = tasks_col.find_one({"task_id": task_id})['reward']
            user_wallet = user.get("wallet")

            # Send reward
            tx_result = send_reward(ADMIN_PRIVATE_KEY, user_wallet, reward)

            if "error" in tx_result:
                logger.error(f"❌ Transaction failed: {tx_result['error']}")
                await query.edit_message_text("❌ Verification passed but reward transfer failed.")
                await query.message.reply_text(
                    f"⚠️ Sorry {query.from_user.first_name}, verification succeeded "
                    f"but the reward transaction failed.\n\nError: {tx_result['error']}"
                )
            else:
                sig = str(tx_result.value)
                explorer_url = f"https://explorer.solana.com/tx/{sig}?cluster=devnet"
                logger.info(f"✅ Transaction successful: {sig}")

                await query.edit_message_text(
                    f"✅ Verified! {reward} Broke Coin sent to your wallet.\n🔗 [View on Explorer]({explorer_url})",
                    parse_mode="Markdown"
                )

            logger.info(f"✅ Task #{task_id} verified for user {telegram_id}, reward={reward}")
            await query.edit_message_text(f"✅ Verified! {reward} Broke Coin sent to your wallet.")
              # Also send a group message so it's visible like failure messages
            await query.message.reply_text(
                f"🎉 Congratulations {query.from_user.first_name}!! "
                f"You have completed Task #{task_id}.\n\n"
                f"💰 Reward: {reward} Broke Coin has been added to your wallet."
            )
        else:
            logger.warning(f"❌ Task #{task_id} verification failed for user {telegram_id}, comment_ok={comment_ok}, retweet_ok={retweet_ok}")
            await query.message.reply_text(
                f"❌ {update.callback_query.from_user.first_name}, verification failed. "
                "Make sure you commented '$Broke' and retweeted the post."
            )

# ---------------- MAIN ----------------
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("register", register))
    app.add_handler(CommandHandler("add_task", add_task))  # Admin only, private chat
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button))
    logger.info("🤖 Bot started and running...")
    app.run_polling()

if __name__ == "__main__":
    main()
