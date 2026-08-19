import os
import traceback
from datetime import datetime, timezone

from playwright.async_api import async_playwright

from .parser import clean_body
from db.mongodb.crud import save_news
from db.mongodb.crud_channels import get_active_channels, mark_channel_scraped
from db.mongodb.mogo import scrape_errors_collection

headless = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() == "true"

MAX_RETRIES_PER_CHANNEL = 2
BASE_URL = "https://web.bale.ai"
DIALOG_SELECTOR = '[aria-label="dialog-item"]'
MESSAGE_SELECTOR = ".message-item"


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


async def _ensure_channel_list_visible(page) -> None:
    """قبل از رفتن سراغ هر کانال، همیشه به صفحه‌ی اصلی برمی‌گردیم و صبر
    می‌کنیم لیست چت‌ها (dialog-item) واقعاً روی صفحه لود بشه. این کار رو
    بی‌قید و شرط انجام می‌دیم (نه فقط وقتی count==0)، چون بعد از باز شدن
    یک چت، لیست ممکنه هنوز تو DOM باشه ولی state داخلیش (مثل اسکرول یا
    فیلتر) خراب شده باشه."""

    await page.goto(BASE_URL)
    await page.wait_for_selector(DIALOG_SELECTOR, timeout=15000)


async def _get_oldest_rendered_date(page) -> int | None:
    """قدیمی‌ترین data-date بین پیام‌های فعلاً رندرشده در DOM رو برمی‌گردونه.
    برای تشخیص اینکه آیا موقع اسکرول به کرسر (last_scraped_date) رسیدیم یا نه."""

    return await page.evaluate(
        """(selector) => {
            const els = document.querySelectorAll(selector);
            if (!els.length) return null;
            const dates = Array.from(els)
                .map(e => Number(e.dataset.date))
                .filter(d => !Number.isNaN(d));
            if (!dates.length) return null;
            return Math.min(...dates);
        }""",
        MESSAGE_SELECTOR,
    )


async def _scrape_single_channel(page, channel: dict) -> tuple[int, int]:
    """اسکرپ یک کانال با page مشترک.
    برمی‌گردونه: (تعداد پست‌های ذخیره‌شده، جدیدترین data-date دیده‌شده)."""

    title = channel["عنوان کانال"]
    last_scraped_date = channel.get("last_scraped_date") or 0

    await _ensure_channel_list_visible(page)

    dialog = page.locator(DIALOG_SELECTOR).filter(has_text=title)

    if await dialog.count() == 0:
        raise RuntimeError(f"کانال «{title}» در لیست چت‌ها پیدا نشد")

    await dialog.first.click()
    await page.wait_for_timeout(2000)

    # اسکرول تا زمانی که یا ارتفاع صفحه دیگه تغییر نکنه (به انتهای تاریخچه
    # رسیدیم) یا به کرسر آخرین اسکرپ رسیده باشیم - هر کدوم زودتر
    stable_count = 0
    reached_cursor = last_scraped_date == 0  # اگه کرسر نداریم، این چک رو رد کن (کانال جدید = همه چیز رو بگیر)

    while stable_count < 3 and not reached_cursor:
        old_height = await page.evaluate("document.body.scrollHeight")
        await page.mouse.wheel(0, 5000)
        await page.wait_for_timeout(2000)
        new_height = await page.evaluate("document.body.scrollHeight")

        oldest_date = await _get_oldest_rendered_date(page)
        if oldest_date is not None and oldest_date <= last_scraped_date:
            reached_cursor = True

        stable_count = stable_count + 1 if old_height == new_height else 0

    messages = page.locator(MESSAGE_SELECTOR)
    messages_count = await messages.count()

    saved_count = 0
    max_date_seen = last_scraped_date

    for i in range(messages_count):
        message = messages.nth(i)

        msg_date_raw = await message.get_attribute("data-date")
        msg_date = int(msg_date_raw) if msg_date_raw and msg_date_raw.isdigit() else None

        # پیامی که از قبل اسکرپ شده رو رد کن - هستهٔ منطق دیدوپ
        if msg_date is not None and msg_date <= last_scraped_date:
            continue

        try:
            parsed_news = await clean_body(
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

        effective_date = parsed_news.get("msg_date") or msg_date
        if effective_date is not None:
            max_date_seen = max(max_date_seen, effective_date)

    return saved_count, max_date_seen


async def scrape_all_channels() -> dict:
    """روی همه‌ی کانال‌های فعال با یک browser context مشترک اسکرپ می‌کنه.
    خطای یک کانال بقیه‌ی کانال‌ها رو متوقف نمی‌کنه."""

    channels = get_active_channels()
    summary = {"success": [], "failed": []}

    if not channels:
        return summary

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir="./profile",
            headless=headless,
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(BASE_URL)
        await page.wait_for_timeout(3000)

        for channel in channels:
            channel_id = channel["_id"]
            last_error: Exception | None = None

            for attempt in range(1, MAX_RETRIES_PER_CHANNEL + 1):
                try:
                    saved, last_date = await _scrape_single_channel(page, channel)
                    mark_channel_scraped(
                        channel_id, success=True, last_message_date=last_date
                    )
                    summary["success"].append(
                        {
                            "channel_id": channel_id,
                            "saved": saved,
                            "last_message_date": last_date,
                        }
                    )
                    last_error = None
                    break
                except Exception as e:
                    last_error = e
                    await page.wait_for_timeout(2000)

            if last_error is not None:
                _log_error(channel, last_error)
                mark_channel_scraped(channel_id, success=False)
                summary["failed"].append(
                    {"channel_id": channel_id, "error": str(last_error)}
                )

        await context.close()

    return summary