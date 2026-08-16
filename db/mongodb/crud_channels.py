from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import DuplicateKeyError

from .mogo import channels_collection


def _now():
    return datetime.now(timezone.utc)


def create_channel(data: dict) -> dict:
    data = dict(data)
    data["ایجاد شده در"] = _now()
    data["به‌روزرسانی شده در"] = _now()
    data["آخرین اسکرپ موفق"] = None
    data["وضعیت عضویت"] = "در صف عضویت"
    data["خطای عضویت"] = None
    try:
        result = channels_collection.insert_one(data)
    except DuplicateKeyError:
        raise ValueError("کانالی با این آیدی قبلاً ثبت شده است")
    data["_id"] = str(result.inserted_id)
    return data


def list_channels(status: str | None = None) -> list[dict]:
    query = {}
    if status:
        query["وضعیت"] = status
    docs = list(channels_collection.find(query).sort("_id", -1))
    for d in docs:
        d["_id"] = str(d["_id"])
    return docs


def get_channel(channel_id: str) -> dict | None:
    try:
        oid = ObjectId(channel_id)
    except InvalidId:
        return None
    doc = channels_collection.find_one({"_id": oid})
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc


def update_channel(channel_id: str, updates: dict) -> dict | None:
    try:
        oid = ObjectId(channel_id)
    except InvalidId:
        return None
    updates = {k: v for k, v in updates.items() if v is not None}
    if not updates:
        return get_channel(channel_id)
    updates["به‌روزرسانی شده در"] = _now()

    # اگه آیدی کانال عوض بشه، باید دوباره عضو بشیم
    if "آیدی کانال" in updates:
        updates["وضعیت عضویت"] = "در صف عضویت"
        updates["خطای عضویت"] = None

    try:
        channels_collection.update_one({"_id": oid}, {"$set": updates})
    except DuplicateKeyError:
        raise ValueError("کانالی با این آیدی قبلاً ثبت شده است")
    return get_channel(channel_id)


def delete_channel(channel_id: str) -> bool:
    try:
        oid = ObjectId(channel_id)
    except InvalidId:
        return False
    result = channels_collection.delete_one({"_id": oid})
    return result.deleted_count > 0


def get_active_channels() -> list[dict]:
    """کانال‌هایی که باید توسط زمان‌بند اسکرپ بشن."""
    return list_channels(status="فعال")


def mark_channel_scraped(channel_id: str, success: bool) -> None:
    """فقط در صورت موفقیت کامل، تاریخ آخرین اسکرپ موفق آپدیت می‌شود.
    این یعنی اگه یه دور fail بشه، دور بعدی خودش دوباره تلاش می‌کنه."""
    try:
        oid = ObjectId(channel_id)
    except InvalidId:
        return
    if success:
        channels_collection.update_one(
            {"_id": oid},
            {"$set": {"آخرین اسکرپ موفق": _now()}},
        )


def update_membership_status(
    channel_id: str, status: str, error: str | None = None
) -> None:
    try:
        oid = ObjectId(channel_id)
    except InvalidId:
        return
    channels_collection.update_one(
        {"_id": oid},
        {"$set": {"وضعیت عضویت": status, "خطای عضویت": error}},
    )