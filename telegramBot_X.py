# broke_task_bot_v23.py
import logging
import requests
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

# ---------------- LOGGING ----------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------------- CONFIG ----------------
TELEGRAM_TOKEN = "8448248703:AAHomMs8NQvp0ILw2mVIJhlpJUxDdoq-W7A"
X_BEARER_TOKEN = "AAAAAAAAAAAAAAAAAAAAALH74QEAAAAAz8ldp%2FYEz%2BBenewoQ003Uts1sv4%3DDbCvfD9XUlnPpwuIh08TxUOB2zTZqCn3gCYREwXWZE8lJ1PMzs"
BOT_WALLET = "CnQbz6eS3UvUbXewVCN861ue2qXZ2EG7s5Lkxp4hDExD"

# ---------------- GROUP CONFIG ----------------
GROUP_ID = -4927456409  # Replace with your group chat ID

# ---------------- ADMIN CONFIG ----------------
ADMINS = [5864326175]  # Telegram ID(s) of admin(s)

# ---------------- MONGO DB ----------------
client = MongoClient("mongodb://localhost:27017/")
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
    await context.bot.send_message(
        chat_id=GROUP_ID,
        text=f"📌 New Task #{task_id}!\nReward: {reward} Broke Coin\nTweet: {tweet_url}",
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
            logger.info(f"✅ Task #{task_id} verified for user {telegram_id}, reward={reward}")
            await query.edit_message_text(f"✅ Verified! {reward} Broke Coin sent to your wallet.")
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
