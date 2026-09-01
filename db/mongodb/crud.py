import hashlib
import re

from datetime import datetime
from time import perf_counter
from typing import Optional

from .mogo import news_collection


def generate_content_hash(
    title: str,
    body: str,
) -> str:
    content = (
        f"{title.strip()}|{body.strip()}"
    )

    return hashlib.sha256(
        content.encode("utf-8")
    ).hexdigest()


def save_news(
    news: dict,
) -> bool:

    title = (
        news.get("title") or ""
    ).strip()

    body = (
        news.get("body") or ""
    ).strip()

    # If title is empty, use body as title.
    if not title and body:
        title = body

    # If body is empty, use title as body.
    if not body and title:
        body = title

    # Ignore completely empty news.
    if not title and not body:
        return False

    content_hash = generate_content_hash(
        title,
        body,
    )

    document = {
        "title": title,
        "body": body,
        "link": news.get("link"),
        "category": news.get("category"),
        "source_type": news.get("source_type"),
        "published_at": news.get("published_at"),
        "content_hash": content_hash,
    }

    try:

        news_collection.insert_one(
            document
        )

        return True

    except Exception as e:

        # Duplicate news.
        if "duplicate key" in str(e).lower():
            return False

        raise


def get_news_from_db(
    page_number: int = 1,
    page_size: int = 10,
    q: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> dict:
    """
    Returns a paginated list of news, newest first.

    q:
        Optional search query.
        Searches in both title and body.

    page_number:
        1-based page index.

    page_size:
        Number of items per page.

    start_date / end_date:
        Optional bounds filtered against published_at.

        published_at is stored as a real timezone-aware
        datetime in MongoDB.

        Parsing and validating incoming date strings into
        datetime objects is handled by the API layer.
    """

    # ----------------------------------------------
    # Start timer
    # ----------------------------------------------

    start_time = perf_counter()

    # ----------------------------------------------
    # Pagination validation
    # ----------------------------------------------

    if (
        page_number is None
        or page_number < 1
    ):
        page_number = 1

    if (
        page_size is None
        or page_size < 1
    ):
        page_size = 10

    # ----------------------------------------------
    # Base MongoDB query
    # ----------------------------------------------

    query = {}

    # ----------------------------------------------
    # Search
    # ----------------------------------------------

    if q and q.strip():

        search_text = q.strip()

        # Treat q as normal text instead of raw regex.
        escaped_search_text = re.escape(
            search_text
        )

        query["$or"] = [
            {
                "title": {
                    "$regex": escaped_search_text,
                    "$options": "i",
                }
            },
            {
                "body": {
                    "$regex": escaped_search_text,
                    "$options": "i",
                }
            },
        ]

    # ----------------------------------------------
    # Date filter
    # ----------------------------------------------

    date_filter = {}

    if start_date:

        date_filter["$gte"] = start_date

    if end_date:

        date_filter["$lte"] = end_date

    if date_filter:

        query["published_at"] = date_filter

    # ----------------------------------------------
    # Pagination
    # ----------------------------------------------

    skip = (
        page_number - 1
    ) * page_size

    # ----------------------------------------------
    # Total count
    # ----------------------------------------------

    total_count = (
        news_collection.count_documents(
            query
        )
    )

    # ----------------------------------------------
    # Get records
    # ----------------------------------------------

    cursor = (
        news_collection
        .find(
            query,
            {
                "_id": 0,
                "content_hash": 0,
            },
        )
        .sort(
            "_id",
            -1,
        )
        .skip(skip)
        .limit(page_size)
    )

    records = list(cursor)

    # ----------------------------------------------
    # Calculate total pages
    # ----------------------------------------------

    total_page = (
        (
            total_count
            + page_size
            - 1
        )
        // page_size
        if page_size
        else 0
    )

    # ----------------------------------------------
    # Calculate execution time
    # ----------------------------------------------

    time_elapsed = (
        perf_counter()
        - start_time
    )

    # ----------------------------------------------
    # Response
    # ----------------------------------------------

    return {
        "_metadata": {
            "total_count": total_count,
            "total_page": total_page,
            "page_number": page_number,
            "per_page": page_size,
            "time_elapsed": round(
                time_elapsed,
                5,
            ),
        },
        "records": records,
    }