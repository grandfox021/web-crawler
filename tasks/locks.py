import logging
from datetime import datetime, timedelta, timezone

from pymongo.errors import DuplicateKeyError

from db.mongodb.mogo import lock_collection


logger = logging.getLogger(__name__)

LOCK_ID = "bale_scrape_lock"


def acquire_lock(timeout_seconds: int) -> bool:
    """
    تلاش می‌کنه قفل رو بگیره.
    اگه قفل آزاده یا منقضی شده باشه، می‌گیرتش و True برمی‌گردونه.
    اگه یکی دیگه قفل رو داره (و منقضی نشده)، False برمی‌گردونه.
    """

    now = datetime.now(timezone.utc)
    expire_at = now + timedelta(seconds=timeout_seconds)

    try:
        # اگه رکورد وجود نداره یا expire_at‌ش گذشته، بگیرش
        result = lock_collection.find_one_and_update(
            {
                "_id": LOCK_ID,
                "expire_at": {"$lte": now},
            },
            {
                "$set": {
                    "expire_at": expire_at,
                    "locked_at": now,
                }
            },
        )

        if result is not None:
            return True

        # اگه رکورد اصلاً وجود نداشت (اولین بار)
        lock_collection.insert_one(
            {
                "_id": LOCK_ID,
                "expire_at": expire_at,
                "locked_at": now,
            }
        )
        return True

    except DuplicateKeyError:
        # یکی دیگه هم‌زمان همین لحظه قفل رو گرفته
        return False


def release_lock():
    lock_collection.delete_one({"_id": LOCK_ID})