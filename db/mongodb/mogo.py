import os

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()


MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "bale_crawler")
MONGO_COLLECTION_NAME = os.getenv("MONGO_COLLECTION_NAME", "news")
MONGO_USERNAME = os.getenv("MONGO_USERNAME")
MONGO_PASSWORD = os.getenv("MONGO_PASSWORD")


client = MongoClient(
    MONGO_URI,
    username=MONGO_USERNAME,
    password=MONGO_PASSWORD,
)

db = client[MONGO_DB_NAME]

news_collection = db[MONGO_COLLECTION_NAME]
lock_collection = db["scrape_locks"]
channels_collection = db["channels"]
scrape_errors_collection = db["scrape_errors"]

# جلوگیری از ذخیره خبر تکراری
news_collection.create_index(
    "هش عنوان",
    unique=True,
)

# قفل‌های منقضی‌شده به‌صورت خودکار پاک بشن
lock_collection.create_index(
    "expire_at",
    expireAfterSeconds=0,
)

# هر آیدی کانال فقط یک‌بار می‌تواند ثبت شود
channels_collection.create_index(
    "آیدی کانال",
    unique=True,
)

# خطاهای اسکرپ هم بعد از مدتی پاک بشن (اختیاری - مثلا ۳۰ روز)
scrape_errors_collection.create_index(
    "created_at",
    expireAfterSeconds=60 * 60 * 24 * 30,
)