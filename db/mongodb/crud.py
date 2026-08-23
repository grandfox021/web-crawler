import hashlib
from datetime import datetime
from typing import Optional

from .mogo import news_collection


def generate_content_hash(title: str, body: str) -> str:
    content = f"{title.strip()}|{body.strip()}"
    return hashlib.sha256(
        content.encode("utf-8")
    ).hexdigest()


def save_news(news: dict) -> bool:

    title = (news.get("title") or "").strip()
    body = (news.get("body") or "").strip()

    if not title and body:
        title = body

    if not body and title:
        body = title

    if not title and not body:
        return False

    content_hash = generate_content_hash(title, body)

    document = {
        "title": title,
        "body": body,
        "link": news.get("link"),
        "source": news.get("source"),
        "source_type": news.get("source_type"),
        "published_at": news.get("published_at"),
        "content_hash": content_hash,
    }

    try:
        news_collection.insert_one(document)
        return True

    except Exception as e:
        if "duplicate key" in str(e).lower():
            return False
        raise


def get_news_from_db(
    page_number: int = 1,
    page_size: int = 10,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> dict:
    """
    Returns a paginated list of news, newest first.

    page_number: 1-based page index (defaults to 1)
    page_size: number of items per page (defaults to 10)
    start_date / end_date: optional bounds filtered against "published_at",
        which is stored as a real (timezone-aware) datetime - not a string.
        Parsing/validating incoming date strings into datetime objects is
        the API layer's job (see api/routes.py); this function expects
        actual datetime instances.
    """

    if page_number is None or page_number < 1:
        page_number = 1

    if page_size is None or page_size < 1:
        page_size = 10

    query = {}
    date_filter = {}

    if start_date:
        date_filter["$gte"] = start_date

    if end_date:
        date_filter["$lte"] = end_date

    if date_filter:
        query["published_at"] = date_filter

    skip = (page_number - 1) * page_size

    total_items = news_collection.count_documents(query)

    cursor = (
        news_collection
        .find(
            query,
            {
                "_id": 0,
                "content_hash": 0,
            }
        )
        .sort("_id", -1)
        .skip(skip)
        .limit(page_size)
    )

    total_pages = (total_items + page_size - 1) // page_size if page_size else 0

    return {
        "items": list(cursor),
        "page_number": page_number,
        "page_size": page_size,
        "total_items": total_items,
        "total_pages": total_pages,
    }