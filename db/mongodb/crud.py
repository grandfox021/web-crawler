import hashlib

from .mogo import news_collection


def generate_content_hash(title: str, body: str) -> str:
    content = f"{title.strip()}|{body.strip()}"
    return hashlib.sha256(
        content.encode("utf-8")
    ).hexdigest()


def save_news(news: dict) -> bool:

    title = (news.get("عنوان") or "").strip()
    body = (news.get("متن") or "").strip()

    if not title and body:
        title = body

    if not body and title:
        body = title

    if not title and not body:
        return False

    content_hash = generate_content_hash(title, body)

    document = {
        "عنوان": title,
        "متن": body,
        "لینک": news.get("لینک"),
        "منبع": news.get("منبع"),
        "نوع منبع": news.get("نوع منبع"),
        "تاریخ انتشار": news.get("تاریخ انتشار"),
        "هش عنوان": content_hash,
    }

    try:
        news_collection.insert_one(document)
        return True

    except Exception as e:
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
                "هش عنوان": 0,
            }
        )
        .sort("_id", -1)
        .limit(limit)
    )

    return list(cursor)