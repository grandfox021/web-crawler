import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from db.mongodb import crud_channels
from db.mongodb.channel import ChannelCreate, ChannelUpdate
from scraper.locks import acquire_lock, release_lock
from scraper.channel_membership import join_channel_in_bale

router = APIRouter(prefix="/channels", tags=["channels"])

# چون عضویت هم از همون پروفایل پلی‌رایت اسکرپ استفاده می‌کنه، باید با همون
# قفل هماهنگ بشه تا با یه اسکرپ در حال اجرا تداخل پیدا نکنه
JOIN_LOCK_TIMEOUT = int(os.getenv("JOIN_LOCK_TIMEOUT", "120"))


def _try_join(bale_id: str) -> bool:
    """
    تلاش برای عضویت در کانال بله.
    فقط اگر موفق شد True برمی‌گرداند.
    """
    if not acquire_lock(JOIN_LOCK_TIMEOUT):
        raise HTTPException(
            status_code=409,
            detail="یک اجرای اسکرپ یا عضویت دیگر در حال انجام است."
        )
    try:
        result = join_channel_in_bale(bale_id)
        if not result:
            raise HTTPException(
                status_code=502,
                detail="عضویت در کانال بله انجام نشد"
            )
        return True
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"خطا در عضویت بله: {str(e)}"
        )
    finally:
        release_lock()

@router.post("", status_code=201)
def create_channel(payload: ChannelCreate):
    data = payload.dict(by_alias=True)

    existing_channel = crud_channels.get_channel_by_bale_id(data.get("آیدی کانال"))
    if existing_channel:
        raise HTTPException(400 , "این کانال در دیتابیس وجود دارد")


    # اول عضو شدن در بله
    _try_join(data["آیدی کانال"])
    # فقط بعد از موفقیت join ذخیره کن
    try:
        doc = crud_channels.create_channel(data)

    except ValueError as e:
        raise HTTPException(
            status_code=409,
            detail=str(e)
        )
    # چون join موفق بوده
    crud_channels.update_membership_status(
        doc["_id"],
        "عضو شد"
    )
    return crud_channels.get_channel(doc["_id"])
@router.get("")
def list_channels(status: Optional[str] = Query(default=None, alias="وضعیت")):
    return crud_channels.list_channels(status=status)


@router.get("/{channel_id}")
def get_channel(channel_id: str):
    doc = crud_channels.get_channel(channel_id)
    if not doc:
        raise HTTPException(status_code=404, detail="کانال پیدا نشد")
    return doc


@router.get("get_channel_by_balechannel_id/{bale_channel_id}")
def get_channel_by_balechannel_id(bale_channel_id: str):
    doc = crud_channels.get_channel_by_bale_id(bale_channel_id)
    if not doc:
        raise HTTPException(status_code=404, detail="کانال پیدا نشد")
    return doc

@router.patch("/{channel_id}")
def update_channel(channel_id: str, payload: ChannelUpdate):
    updates = payload.dict(by_alias=True, exclude_unset=True)

    try:
        doc = crud_channels.update_channel(channel_id, updates)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    if not doc:
        raise HTTPException(status_code=404, detail="کانال پیدا نشد")

    # اگه آیدی کانال عوض شده باشه، باید دوباره عضو بشیم
    if "آیدی کانال" in updates:
        _try_join(channel_id, doc["آیدی کانال"])
        doc = crud_channels.get_channel(channel_id)

    return doc


@router.post("/{channel_id}/rejoin")
def rejoin_channel(channel_id: str):
    """تلاش دستی مجدد برای عضویت، مثلا وقتی 'خطا در عضویت' یا
    'در صف عضویت' مونده باشه."""

    doc = crud_channels.get_channel(channel_id)
    if not doc:
        raise HTTPException(status_code=404, detail="کانال پیدا نشد")

    if not acquire_lock(JOIN_LOCK_TIMEOUT):
        raise HTTPException(
            status_code=409,
            detail="یک اجرای اسکرپ یا عضویت دیگر در حال انجام است.",
        )

    try:
        join_channel_in_bale(doc["آیدی کانال"])
        crud_channels.update_membership_status(channel_id, "عضو شد")
    except Exception as e:
        crud_channels.update_membership_status(
            channel_id, "خطا در عضویت", error=str(e)
        )
        raise HTTPException(status_code=502, detail=str(e))
    finally:
        release_lock()

    return crud_channels.get_channel(channel_id)


@router.delete("/{channel_id}", status_code=204)
def delete_channel(channel_id: str):
    ok = crud_channels.delete_channel(channel_id)
    if not ok:
        raise HTTPException(status_code=404, detail="کانال پیدا نشد")

