import os
from typing import Optional

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
)

from db.mongodb import crud_channels
from db.mongodb.channel import (
    ChannelCreate,
    ChannelUpdate,
)
from scraper.channel_membership import (
    join_channel_in_bale,
)
from scraper.locks import (
    acquire_lock,
    release_lock,
)


router = APIRouter(
    prefix="/channels",
    tags=["channels"],
)


# چون join و scraper هر دو از profile مشترک
# Playwright استفاده می‌کنند، باید با همان lock
# هماهنگ باشند.
JOIN_LOCK_TIMEOUT = int(
    os.getenv(
        "JOIN_LOCK_TIMEOUT",
        "120",
    )
)


def _try_join(
    bale_id: str,
) -> bool:
    """
    تلاش برای عضویت در کانال Bale.

    اگر lock گرفته نشود، یعنی scraper یا عملیات
    عضویت دیگری در حال اجراست.
    """

    if not acquire_lock(
        JOIN_LOCK_TIMEOUT
    ):

        raise HTTPException(
            status_code=409,
            detail=(
                "یک اجرای اسکرپ یا عضویت "
                "دیگر در حال انجام است."
            ),
        )

    try:

        result = join_channel_in_bale(
            bale_id
        )

        if not result:

            raise HTTPException(
                status_code=502,
                detail=(
                    "عضویت در کانال بله انجام نشد"
                ),
            )

        return True

    except HTTPException:
        raise

    except Exception as e:

        raise HTTPException(
            status_code=502,
            detail=(
                f"خطا در عضویت بله: {str(e)}"
            ),
        )

    finally:

        release_lock()


@router.post(
    "",
    status_code=201,
)
def create_channel(
    payload: ChannelCreate,
):
    """
    ایجاد کانال:

        1. join
        2. اگر join موفق بود -> save Mongo
    """


    data = payload.dict(
        by_alias=True
    )

    existing_channel = crud_channels.get_channel_by_bale_id(data.get("آیدی کانال"))
    if existing_channel:
        raise HTTPException(400 , "این کانال در دیتابیس وجود دارد")


    # data = payload.dict(
    #     by_alias=True
    # )

    # ----------------------------------------------
    # ابتدا join
    # ----------------------------------------------

    _try_join(
        data["آیدی کانال"]
    )

    # ----------------------------------------------
    # سپس ذخیره در Mongo
    # ----------------------------------------------

    try:

        doc = crud_channels.create_channel(
            data
        )

    except ValueError as e:

        raise HTTPException(
            status_code=409,
            detail=str(e),
        )

    # ----------------------------------------------
    # وضعیت عضویت
    # ----------------------------------------------

    crud_channels.update_membership_status(
        doc["_id"],
        "عضو شد",
    )

    return crud_channels.get_channel(
        doc["_id"]
    )


@router.get("")
def list_channels(
    status: Optional[str] = Query(
        default=None,
        alias="وضعیت",
    ),
):
    """
    لیست کانال‌ها.
    """

    return crud_channels.list_channels(
        status=status
    )


@router.get(
    "/{channel_id}"
)
def get_channel(
    channel_id: str,
):
    """
    دریافت کانال با ID داخلی Mongo.
    """

    doc = crud_channels.get_channel(
        channel_id
    )

    if not doc:

        raise HTTPException(
            status_code=404,
            detail="کانال پیدا نشد",
        )

    return doc


@router.get(
    "/get_channel_by_balechannel_id/"
    "{bale_channel_id}"
)
def get_channel_by_balechannel_id(
    bale_channel_id: str,
):
    """
    دریافت کانال با آیدی Bale.
    """

    doc = (
        crud_channels
        .get_channel_by_bale_id(
            bale_channel_id
        )
    )

    if not doc:

        raise HTTPException(
            status_code=404,
            detail="کانال پیدا نشد",
        )

    return doc


@router.patch(
    "/{channel_id}"
)
def update_channel(
    channel_id: str,
    payload: ChannelUpdate,
):
    """
    بروزرسانی کانال.

    اگر آیدی Bale تغییر کند:
        1. cursor پاک می‌شود
        2. کانال باید دوباره join شود
    """

    updates = payload.dict(
        by_alias=True,
        exclude_unset=True,
    )

    try:

        doc = crud_channels.update_channel(
            channel_id,
            updates,
        )

    except ValueError as e:

        raise HTTPException(
            status_code=409,
            detail=str(e),
        )

    if not doc:

        raise HTTPException(
            status_code=404,
            detail="کانال پیدا نشد",
        )

    # ----------------------------------------------
    # تغییر آیدی Bale
    # ----------------------------------------------

    if "آیدی کانال" in updates:

        _try_join(
            doc["آیدی کانال"]
        )

        doc = crud_channels.get_channel(
            channel_id
        )

    return doc


@router.post(
    "/{channel_id}/rejoin"
)
def rejoin_channel(
    channel_id: str,
):
    """
    عضویت مجدد دستی در کانال.
    """

    doc = crud_channels.get_channel(
        channel_id
    )

    if not doc:

        raise HTTPException(
            status_code=404,
            detail="کانال پیدا نشد",
        )

    if not acquire_lock(
        JOIN_LOCK_TIMEOUT
    ):

        raise HTTPException(
            status_code=409,
            detail=(
                "یک اجرای اسکرپ یا عضویت "
                "دیگر در حال انجام است."
            ),
        )

    try:

        result = join_channel_in_bale(
            doc["آیدی کانال"]
        )

        if not result:

            raise RuntimeError(
                "عضویت در کانال بله انجام نشد"
            )

        crud_channels.update_membership_status(
            channel_id,
            "عضو شد",
        )

    except Exception as e:

        crud_channels.update_membership_status(
            channel_id,
            "خطا در عضویت",
            error=str(e),
        )

        raise HTTPException(
            status_code=502,
            detail=str(e),
        )

    finally:

        release_lock()

    return crud_channels.get_channel(
        channel_id
    )


@router.delete(
    "/{channel_id}",
    status_code=204,
)
def delete_channel(
    channel_id: str,
):
    """
    حذف کانال.
    """

    ok = crud_channels.delete_channel(
        channel_id
    )

    if not ok:

        raise HTTPException(
            status_code=404,
            detail="کانال پیدا نشد",
        )