from datetime import datetime, timezone
from time import perf_counter
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId

from .mogo import channels_collection


def _serialize(doc: dict) -> dict:
    doc = dict(doc)
    doc["_id"] = str(doc["_id"])
    return doc


def _to_object_id(channel_id: str) -> Optional[ObjectId]:
    try:
        return ObjectId(channel_id)
    except (InvalidId, TypeError):
        return None


def get_channel_by_channel_id(channel_id: str) -> Optional[dict]:
    """Look up a channel by its Bale channel_id (e.g. '@iribnews')."""
    doc = channels_collection.find_one({"channel_id": channel_id})
    return _serialize(doc) if doc else None


def create_channel(data: dict) -> dict:
    """Insert a new channel document. Raises ValueError if channel_id already exists."""
    document = {
        **data,
        "membership_status": None,
        "membership_error": None,
        "created_at": datetime.now(timezone.utc),
    }

    try:
        result = channels_collection.insert_one(document)
    except Exception as e:
        if "duplicate key" in str(e).lower():
            raise ValueError("This channel already exists in the database")
        raise

    document["_id"] = result.inserted_id
    return _serialize(document)


def get_channel(channel_id: str) -> Optional[dict]:
    """Look up a channel by its internal Mongo _id."""
    object_id = _to_object_id(channel_id)
    if object_id is None:
        return None

    doc = channels_collection.find_one({"_id": object_id})
    return _serialize(doc) if doc else None


def list_channels(
    is_active: Optional[bool] = None,
    q: Optional[str] = None,
    page_number: int = 1,
    page_size: int = 10,
) -> dict:
    """
    Paginated channel listing, newest first.

    q: optional case-insensitive search matched against title OR description.
    """
    if page_number is None or page_number < 1:
        page_number = 1

    if page_size is None or page_size < 1:
        page_size = 10

    query = {}
    if is_active is not None:
        query["is_active"] = is_active

    if q:
        query["$or"] = [
            {"title": {"$regex": q, "$options": "i"}},
            {"description": {"$regex": q, "$options": "i"}},
        ]

    started_at = perf_counter()

    skip = (page_number - 1) * page_size
    total_count = channels_collection.count_documents(query)

    cursor = (
        channels_collection
        .find(query)
        .sort("_id", -1)
        .skip(skip)
        .limit(page_size)
    )

    records = [_serialize(doc) for doc in cursor]

    time_elapsed = perf_counter() - started_at

    total_page = (total_count + page_size - 1) // page_size if page_size else 0

    return {
        "_metadata": {
            "total_count": total_count,
            "total_page": total_page,
            "page_number": page_number,
            "per_page": page_size,
            "time_elapsed": round(time_elapsed, 5),
        },
        "records": records,
    }


def update_channel(channel_id: str, updates: dict) -> Optional[dict]:
    """Partial update. Raises ValueError if the new channel_id collides with another channel."""
    object_id = _to_object_id(channel_id)
    if object_id is None:
        return None

    if not updates:
        return get_channel(channel_id)

    try:
        result = channels_collection.update_one(
            {"_id": object_id},
            {"$set": updates},
        )
    except Exception as e:
        if "duplicate key" in str(e).lower():
            raise ValueError("Another channel already uses this channel_id")
        raise

    if result.matched_count == 0:
        return None

    return get_channel(channel_id)


def update_membership_status(
    channel_id: str,
    status: str,
    error: Optional[str] = None,
) -> None:
    object_id = _to_object_id(channel_id)
    if object_id is None:
        return

    channels_collection.update_one(
        {"_id": object_id},
        {
            "$set": {
                "membership_status": status,
                "membership_error": error,
            }
        },
    )


def delete_channel(channel_id: str) -> bool:
    object_id = _to_object_id(channel_id)
    if object_id is None:
        return False

    result = channels_collection.delete_one({"_id": object_id})
    return result.deleted_count > 0


def get_active_channels() -> list:
    """
    Return all active channels for internal scraper use.
    Unlike list_channels(), this returns raw Mongo documents
    (ObjectId _id kept as-is) since the scraper needs to pass
    _id straight back into mark_channel_scraped().
    """
    return list(channels_collection.find({"is_active": True}))


def mark_channel_scraped(
    channel_id,
    success: bool,
    last_message_date: Optional[int] = None,
) -> None:
    """
    Record the outcome of a scrape attempt for a channel.

    channel_id: the Mongo _id of the channel (ObjectId or str),
    as returned by get_active_channels().
    last_message_date: only persisted as the new cursor when success=True,
    so a failed run never corrupts the existing cursor.
    """
    object_id = (
        channel_id
        if isinstance(channel_id, ObjectId)
        else _to_object_id(str(channel_id))
    )
    if object_id is None:
        return

    update = {
        "last_scraped_at": datetime.now(timezone.utc),
        "last_scrape_success": success,
    }

    if success and last_message_date is not None:
        update["last_scraped_date"] = last_message_date

    channels_collection.update_one(
        {"_id": object_id},
        {"$set": update},
    )