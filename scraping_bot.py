# broke_task_bot_scraping.py
import logging
import subprocess
import sys
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
import snscrape.modules.twitter as sntwitter
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import time

# ---------------- LOGGING ----------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------------- CONFIG ----------------
TELEGRAM_TOKEN = "8448248703:AAHomMs8NQvp0ILw2mVIJhlpJUxDdoq-W7A"
GROUP_ID = -4927456409  # Replace with your group chat ID
ADMINS = [5864326175]   # Replace with admin Telegram IDs

# ---------------- MONGO DB ----------------
client = MongoClient("mongodb://localhost:27017/")
db = client['broke_bot']
users_col = db['users']
tasks_col = db['tasks']
claims_col = db['claims']

# ---------------- HELPER FUNCTION ----------------
def get_next_task_id():
    last_task = tasks_col.find_one(sort=[("task_id", -1)])
    return last_task["task_id"] + 1 if last_task else 1

# ---------------- VERIFICATION WITH SCRAPING ----------------

# ---------------- VERIFICATION WITH SELENIUM ----------------
def verify_x_comment(tweet_url, username):
    """
    Open a tweet with Selenium, scrape replies, and check if user commented exactly "NoDoubt".
    """

    options = Options()
    options.add_argument("--headless=new")  # use headless mode
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    try:
        driver.get(tweet_url)
        time.sleep(6)  # wait for page + comments to load

        # Scroll to load more replies (increase the scroll count)
        for _ in range(5):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(3)

        # Get all replies
        replies = driver.find_elements(By.XPATH, '//article[@data-testid="tweet"]')

        found = False
        for reply in replies:
            try:
                # Extract username (handle and display name are different, so let's be precise)
                user_elem = reply.find_element(By.XPATH, './/div[@data-testid="User-Name"]//span').text.strip()
                text_elem = reply.find_element(By.XPATH, './/div[@data-testid="tweetText"]').text.strip()

                print(f"👉 Found reply by: {user_elem} | Text: {text_elem}")  # Debug log

                # Strict check: username match + exact "NoDoubt"
                if user_elem.lower() == username.lower() and "NoDoubt" == text_elem:
                    print(f"✅ {username} commented correctly with 'NoDoubt'")
                    found = True
                    break
            except Exception as e:
                print(f"Error while processing reply: {e}")
                continue

        if not found:
            print(f"❌ {username} did not comment correctly")
        return found

    except Exception as e:
        print(f"Scraping failed: {e}")
        return False

    finally:
        driver.quit()
# def verify_x_retweet(tweet_id, username):
#     """Check if user retweeted using snscrape."""
#     try:
#         query = f"from:{username} url:twitter.com/*/status/{tweet_id}"
#         for tweet in sntwitter.TwitterSearchScraper(query).get_items():
#             if hasattr(tweet, "retweetedTweet") and str(tweet.retweetedTweet.id) == str(tweet_id):
#                 logger.info(f"✅ {username} retweeted {tweet_id}")
#                 return True
#         logger.warning(f"❌ {username} did not retweet {tweet_id}")
#         return False
#     except Exception as e:
#         logger.error(f"Scraping retweet failed: {e}")
#         return False

# ---------------- TELEGRAM HANDLERS ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome! Use /register to register your X username and wallet.")

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send your X username and wallet address in this format:\nusername,wallet_address")

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
        await update.message.reply_text(f"✅ Registered X username: {x_username.strip()} and wallet: {wallet.strip()}")
    except Exception as e:
        await update.message.reply_text("❌ Format incorrect. Use: username,wallet_address")

async def add_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.message.from_user.id
    if telegram_id not in ADMINS:
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

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split("|")
    
    if data[0] == "verify":
        task_id = int(data[1])
        telegram_id = query.from_user.id
        user = users_col.find_one({"telegram_id": telegram_id})
        if not user:
            await query.message.reply_text("❌ You are not registered. Use /register first.")
            return

        claim = claims_col.find_one({"task_id": task_id})
        if telegram_id in claim["telegram_ids"]:
            await query.message.reply_text("❌ You already claimed this task.")
            return

        tweet_url = tasks_col.find_one({"task_id": task_id})["url"]
        username = user["x_username"]

        comment_ok = verify_x_comment(tweet_url, username)

        # retweet_ok = verify_x_retweet(tweet_id, username)
# and retweet_ok
        if comment_ok :
            claims_col.update_one({"task_id": task_id}, {"$push": {"telegram_ids": telegram_id}})
            reward = tasks_col.find_one({"task_id": task_id})['reward']
            await query.edit_message_text(f"✅ Verified! {reward} Broke Coin sent to your wallet.")
        else:
            await query.message.reply_text("❌ Verification failed. Make sure you commented 'NoDoubt' and retweeted.")

# ---------------- MAIN ----------------
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("register", register))
    app.add_handler(CommandHandler("add_task", add_task))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button))
    app.run_polling()

if __name__ == "__main__":
    main()
