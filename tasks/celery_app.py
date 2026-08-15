import os
from celery import Celery
from celery.schedules import crontab
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://guest:geust@localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

# فاصله‌ی اجرای تسک اسکرپ (بر حسب ثانیه) - پیش‌فرض 5 دقیقه
SCRAPE_INTERVAL_SECONDS = int(os.getenv("SCRAPE_INTERVAL_SECONDS", "300"))

celery_app = Celery(
    "bale_crawler",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=["tasks.scraping_tasks"], # اسم پکیج ریشه رو مطابق پروژه‌ت بذار
)

celery_app.conf.update(
    timezone="Asia/Tehran",
    enable_utc=True,
    task_track_started=True,
    worker_max_tasks_per_child=1,
)

celery_app.conf.beat_schedule = {
    "scrape-bale-periodic": {
        "task": "tasks.scraping_tasks.scrape_news_task",
        "schedule": timedelta(seconds=SCRAPE_INTERVAL_SECONDS),
    },
}