import logging
import os

from .celery_app import celery_app
from ..scraper.locks import acquire_lock, release_lock
from scraper.bale_scraper import scrape_news
from db.mongodb.crud import save_news

logger = logging.getLogger(__name__)

LOCK_TIMEOUT = int(os.getenv("SCRAPE_LOCK_TIMEOUT", "600"))       # 10 دقیقه
RETRY_WAIT_SECONDS = int(os.getenv("SCRAPE_RETRY_WAIT", "15"))    # هر چند ثانیه دوباره چک کنه
MAX_WAIT_RETRIES = int(os.getenv("SCRAPE_MAX_WAIT_RETRIES", "40"))  # حداکثر چند بار صبر کنه (40*15=10 دقیقه)


@celery_app.task(
    bind=True,
    max_retries=MAX_WAIT_RETRIES,
)
def scrape_news_task(self):

    if not acquire_lock(LOCK_TIMEOUT):
        logger.info(
            f"اسکرپ قبلی در حال اجراست، {RETRY_WAIT_SECONDS} ثانیه دیگه دوباره تلاش می‌کنم "
            f"(تلاش {self.request.retries + 1} از {MAX_WAIT_RETRIES})"
        )
        raise self.retry(countdown=RETRY_WAIT_SECONDS)

    try:
        try:
            news_list = scrape_news()
        except Exception as exc:
            logger.exception("خطا در اسکرپ")
            release_lock()
            raise self.retry(exc=exc, countdown=60)

        saved_count = 0
        for news in news_list:
            if save_news(news):
                saved_count += 1

        logger.info(f"Total: {len(news_list)}, Saved: {saved_count}")
        return {"total": len(news_list), "saved": saved_count}

    finally:
        release_lock()