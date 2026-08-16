import os

from fastapi import APIRouter, HTTPException

from scraper.bale_scraper import scrape_all_channels
from scraper.locks import acquire_lock, release_lock
from db.mongodb.crud import get_news_from_db


router = APIRouter()

# اگه یه اجرا بیشتر از این طول کشید (مثلا crash کرد و قفل آزاد نشد)،
# قفل به‌صورت خودکار آزاد می‌شه و اجرای بعدی می‌تونه بگیرتش
LOCK_TIMEOUT = int(os.getenv("SCRAPE_LOCK_TIMEOUT", "600"))  # 10 دقیقه


@router.post("/go-scrap")
def go_scrap():
    """Airflow این endpoint رو صدا می‌زنه. تا پایان اسکرپ همه‌ی کانال‌های
    فعال صبر می‌کنه و خلاصه‌ی نتیجه رو برمی‌گردونه.

    نکته: چون کار طولانیه (Playwright + چند کانال)، تایم‌اوت HTTP operator
    توی Airflow و هر ری‌ورس‌پروکسی جلوی این سرویس باید متناسب تنظیم بشه.
    """

    if not acquire_lock(LOCK_TIMEOUT):
        raise HTTPException(
            status_code=409,
            detail="یک اجرای اسکرپ دیگر در حال انجام است.",
        )

    try:
        summary = scrape_all_channels()
    finally:
        release_lock()

    return {
        "channels_succeeded": len(summary["success"]),
        "channels_failed": len(summary["failed"]),
        "details": summary,
    }


@router.get("/get-news-by-limit")
def get_news_by_limit(limit: int = 10):
    result = get_news_from_db(limit)
    return result