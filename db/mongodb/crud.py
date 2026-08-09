import hashlib

#from m import news_collection

from .mogo import news_collection

def generate_content_hash(title: str, body: str) -> str:
    content = f"{title.strip()}|{body.strip()}"

    return hashlib.sha256(
        content.encode("utf-8")
    ).hexdigest()


def save_news(news: dict) -> bool:
    title = (news.get("title") or "").strip()
    body = (news.get("body") or "").strip()

    # اگر title خالی بود
    if not title and body:
        title = body

    # اگر body خالی بود
    if not body and title:
        body = title

    # اگر هر دو خالی بودند، چیزی ذخیره نکن
    if not title and not body:
        return False

    content_hash = generate_content_hash(title, body)

    document = {
        "title": title,
        "body": body,
        "content_hash": content_hash,
    }

    try:
        news_collection.insert_one(document)
        return True

    except Exception as e:
        # اگر خبر تکراری بود
        if "duplicate key" in str(e).lower():
            return False

        raise


def get_news_from_db(limit=10):
    if limit is None:
        limit = 10

    cursor = (
        news_collection
        .find(
            {},
            {
                "_id": 0,
                "content_hash": 0,
            }
        )
        .sort("_id", -1)
        .limit(limit)
    )

    return list(cursor)