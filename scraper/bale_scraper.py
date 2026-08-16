import os
import traceback
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright

from .parser import clean_body
from db.mongodb.crud import save_news
from db.mongodb.crud_channels import get_active_channels, mark_channel_scraped
from db.mongodb.mogo import scrape_errors_collection

headless = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() == "true"

MAX_RETRIES_PER_CHANNEL = 2


def _log_error(channel: dict, error: Exception) -> None:
    scrape_errors_collection.insert_one(
        {
            "channel_id": channel.get("_id"),
            "آیدی کانال": channel.get("آیدی کانال"),
            "عنوان کانال": channel.get("عنوان کانال"),
            "error": str(error),
            "traceback": traceback.format_exc(),
            "created_at": datetime.now(timezone.utc),
        }
    )


def _scrape_single_channel(page, channel: dict) -> int:
    """اسکرپ یک کانال با page مشترک. تعداد پست‌های ذخیره‌شده رو برمی‌گردونه."""

    title = channel["عنوان کانال"]

    dialog = page.locator('[aria-label="dialog-item"]').filter(has_text=title)

    if dialog.count() == 0:
        raise RuntimeError(f"کانال «{title}» در لیست چت‌ها پیدا نشد")

    dialog.first.click()
    page.wait_for_timeout(2000)

    stable_count = 0
    while stable_count < 3:
        old_height = page.evaluate("document.body.scrollHeight")
        page.mouse.wheel(0, 5000)
        page.wait_for_timeout(2000)
        new_height = page.evaluate("document.body.scrollHeight")
        if old_height == new_height:
            stable_count += 1
        else:
            stable_count = 0

    messages = page.locator(".message-item")
    messages_count = messages.count()

    saved_count = 0

    for i in range(messages_count):
        message = messages.nth(i)

        try:
            parsed_news = clean_body(
                message,
                channel_title=title,
                channel_type=channel.get("نوع منبع", "کانال بله"),
            )
        except Exception as e:
            # خطای parse یک پیام نباید بقیه پیام‌های همون کانال رو متوقف کنه
            _log_error(channel, e)
            continue

        if not parsed_news["عنوان"] and not parsed_news["متن"]:
            continue

        # ذخیره فوری هر پیام - اگه ادامه‌ی کار fail بشه، این پیام گم نمی‌شه
        if save_news(parsed_news):
            saved_count += 1

    return saved_count


def scrape_all_channels() -> dict:
    """روی همه‌ی کانال‌های فعال با یک browser context مشترک اسکرپ می‌کنه.
    خطای یک کانال بقیه‌ی کانال‌ها رو متوقف نمی‌کنه."""

    channels = get_active_channels()
    summary = {"success": [], "failed": []}

    if not channels:
        return summary

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir="./profile",
            headless=headless,
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://web.bale.ai")
        page.wait_for_timeout(3000)

        for channel in channels:
            channel_id = channel["_id"]
            last_error: Exception | None = None

            for attempt in range(1, MAX_RETRIES_PER_CHANNEL + 1):
                try:
                    saved = _scrape_single_channel(page, channel)
                    mark_channel_scraped(channel_id, success=True)
                    summary["success"].append(
                        {"channel_id": channel_id, "saved": saved}
                    )
                    last_error = None
                    break
                except Exception as e:
                    last_error = e
                    page.wait_for_timeout(2000)

            if last_error is not None:
                _log_error(channel, last_error)
                mark_channel_scraped(channel_id, success=False)
                summary["failed"].append(
                    {"channel_id": channel_id, "error": str(last_error)}
                )

        context.close()

    return summary