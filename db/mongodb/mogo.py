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


# جلوگیری از ذخیره خبر تکراری
news_collection.create_index(
    "content_hash",
    unique=True,
)