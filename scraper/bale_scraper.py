import os
import traceback
from datetime import datetime, timezone

from playwright.async_api import async_playwright

from .parser import clean_body
from db.mongodb.crud import save_news
from db.mongodb.crud_channels import (
    get_active_channels,
    mark_channel_scraped,
)
from db.mongodb.mogo import scrape_errors_collection


headless = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() == "true"


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

MAX_RETRIES_PER_CHANNEL = 2

# برای تست فعلاً 50 پیام
INITIAL_MESSAGES_LIMIT = 50

# حداکثر تعداد scroll برای جلوگیری از loop بی‌نهایت
MAX_HISTORY_SCROLLS = 100

# مقدار حرکت هر بار
SCROLL_STEP = 1200

# زمان انتظار بعد از scroll
SCROLL_WAIT_MS = 1200

# بعد از باز کردن کانال
CHANNEL_LOAD_WAIT_MS = 2000

BASE_URL = "https://web.bale.ai"

DIALOG_SELECTOR = '[aria-label="dialog-item"]'
MESSAGE_SELECTOR = ".message-item"


# ---------------------------------------------------------
# Logging
# ---------------------------------------------------------

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


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

async def _ensure_channel_list_visible(page) -> None:
    """
    برگشت به صفحه اصلی Bale و اطمینان از وجود لیست کانال‌ها.
    """

    await page.goto(BASE_URL)

    await page.wait_for_selector(
        DIALOG_SELECTOR,
        timeout=15000,
    )


async def _get_message_dates(page) -> list[int]:
    """
    تمام data-date های معتبر پیام‌های فعلی DOM را برمی‌گرداند.

    نکته:
    0 را معتبر حساب نمی‌کنیم.
    """

    return await page.evaluate(
        """
        (selector) => {
            const elements = document.querySelectorAll(selector);

            return Array.from(elements)
                .map(el => Number(el.dataset.date))
                .filter(date => Number.isFinite(date) && date > 0);
        }
        """,
        MESSAGE_SELECTOR,
    )


async def _get_oldest_rendered_date(page) -> int | None:
    """
    قدیمی‌ترین data-date معتبر بین پیام‌های فعلی DOM.
    """

    dates = await _get_message_dates(page)

    if not dates:
        return None

    return min(dates)


async def _get_newest_rendered_date(page) -> int | None:
    """
    جدیدترین data-date معتبر بین پیام‌های فعلی DOM.
    """

    dates = await _get_message_dates(page)

    if not dates:
        return None

    return max(dates)


async def _get_scroll_container(page):
    """
    تلاش می‌کند container واقعی پیام‌ها را پیدا کند.

    به جای تکیه بر document.body، از یکی از message-item ها
    به سمت parent ها حرکت می‌کنیم و اولین عنصر scrollable
    را پیدا می‌کنیم.

    اگر پیدا نشود، document.scrollingElement برگردانده می‌شود.
    """

    return await page.evaluate(
        """
        (messageSelector) => {

            const message = document.querySelector(messageSelector);

            if (!message) {
                return null;
            }

            let current = message.parentElement;

            while (current) {

                const style = window.getComputedStyle(current);

                const overflowY = style.overflowY;

                const isScrollable =
                    (
                        overflowY === "auto" ||
                        overflowY === "scroll" ||
                        overflowY === "overlay"
                    )
                    &&
                    current.scrollHeight > current.clientHeight + 5;

                if (isScrollable) {
                    return current;
                }

                current = current.parentElement;
            }

            return document.scrollingElement || document.documentElement;
        }
        """,
        MESSAGE_SELECTOR,
    )


async def _scroll_messages(page, direction: str) -> bool:
    """
    scroll کردن container پیام‌ها.

    direction:
        "up"
        "down"

    خروجی:
        True  -> scroll انجام شد
        False -> container پیدا نشد
    """

    if direction not in ("up", "down"):
        raise ValueError("direction باید up یا down باشد")

    delta = SCROLL_STEP if direction == "down" else -SCROLL_STEP

    result = await page.evaluate(
        """
        ({messageSelector, delta}) => {

            const message = document.querySelector(messageSelector);

            if (!message) {
                return {
                    ok: false,
                    reason: "message-not-found"
                };
            }

            let container = message.parentElement;

            while (container) {

                const style = window.getComputedStyle(container);

                const overflowY = style.overflowY;

                const isScrollable =
                    (
                        overflowY === "auto" ||
                        overflowY === "scroll" ||
                        overflowY === "overlay"
                    )
                    &&
                    container.scrollHeight > container.clientHeight + 5;

                if (isScrollable) {

                    const before = container.scrollTop;

                    container.scrollBy({
                        top: delta,
                        behavior: "instant"
                    });

                    return {
                        ok: true,
                        before: before,
                        after: container.scrollTop,
                        scrollHeight: container.scrollHeight,
                        clientHeight: container.clientHeight
                    };
                }

                container = container.parentElement;
            }

            const fallback =
                document.scrollingElement ||
                document.documentElement;

            const before = fallback.scrollTop;

            fallback.scrollBy({
                top: delta,
                behavior: "instant"
            });

            return {
                ok: true,
                before: before,
                after: fallback.scrollTop,
                scrollHeight: fallback.scrollHeight,
                clientHeight: fallback.clientHeight
            };
        }
        """,
        {
            "messageSelector": MESSAGE_SELECTOR,
            "delta": delta,
        },
    )

    if not result.get("ok"):
        return False

    await page.wait_for_timeout(SCROLL_WAIT_MS)

    return True


async def _scroll_to_bottom(page) -> None:
    """
    رفتن به انتهای کانال؛ یعنی جدیدترین پیام‌ها.

    چند بار انجام می‌دهیم چون Bale ممکن است lazy-load داشته باشد.
    """

    previous_newest = None
    stable_count = 0

    for i in range(1, 8):

        newest = await _get_newest_rendered_date(page)

        print(
            f"[BALE][BOTTOM] "
            f"scroll={i} "
            f"messages={await page.locator(MESSAGE_SELECTOR).count()} "
            f"oldest={await _get_oldest_rendered_date(page) or 0} "
            f"newest={newest or 0}"
        )

        await _scroll_messages(page, "down")

        await page.wait_for_timeout(500)

        current_newest = await _get_newest_rendered_date(page)

        if current_newest == previous_newest:
            stable_count += 1
        else:
            stable_count = 0

        previous_newest = current_newest

        if stable_count >= 2:
            break

    print("[BALE][BOTTOM] جدیدترین پیام‌ها پیدا شدند.")


# ---------------------------------------------------------
# Message collection
# ---------------------------------------------------------

async def _collect_current_messages(
    page,
    channel: dict,
    last_scraped_date: int | None,
    collected_ids: set[str],
) -> tuple[int, int | None]:
    """
    پیام‌های فعلی DOM را بررسی و ذخیره می‌کند.

    collected_ids:
        برای جلوگیری از پردازش چندباره یک پیام در scroll های مختلف.

    خروجی:
        saved_count
        max_date_seen
    """

    title = channel["عنوان کانال"]

    messages = page.locator(MESSAGE_SELECTOR)

    count = await messages.count()

    saved_count = 0
    max_date_seen = None

    for i in range(count):

        message = messages.nth(i)

        msg_sid = await message.get_attribute("data-sid")
        msg_date_raw = await message.get_attribute("data-date")

        msg_date = None

        if msg_date_raw:
            try:
                parsed_date = int(msg_date_raw)

                if parsed_date > 0:
                    msg_date = parsed_date

            except (TypeError, ValueError):
                msg_date = None

        # -------------------------------------------------
        # cursor
        # -------------------------------------------------

        if msg_date is not None:

            if max_date_seen is None:
                max_date_seen = msg_date
            else:
                max_date_seen = max(
                    max_date_seen,
                    msg_date,
                )

            # کانال قدیمی:
            # هر چیزی که قبلاً scrape شده، رد شود.
            if (
                last_scraped_date is not None
                and msg_date <= last_scraped_date
            ):
                continue

        # -------------------------------------------------
        # شناسه یکتا برای همین اجرای scraper
        # -------------------------------------------------

        unique_id = msg_sid or (
            f"date:{msg_date}"
            if msg_date is not None
            else f"index:{i}"
        )

        if unique_id in collected_ids:
            continue

        collected_ids.add(unique_id)

        # -------------------------------------------------
        # Parse
        # -------------------------------------------------

        try:

            parsed_news = await clean_body(
                message,
                channel_title=title,
                channel_type=channel.get(
                    "نوع منبع",
                    "کانال بله",
                ),
            )

        except Exception as e:

            _log_error(channel, e)

            print(
                f"[BALE][PARSE_ERROR] "
                f"channel={title} "
                f"index={i} "
                f"error={e}"
            )

            continue

        if (
            not parsed_news.get("عنوان")
            and not parsed_news.get("متن")
        ):
            continue

        # -------------------------------------------------
        # Save
        # -------------------------------------------------

        try:

            saved = save_news(parsed_news)

            if saved:
                saved_count += 1

        except Exception as e:

            _log_error(channel, e)

            print(
                f"[BALE][SAVE_ERROR] "
                f"channel={title} "
                f"error={e}"
            )

    return saved_count, max_date_seen


# ---------------------------------------------------------
# NEW CHANNEL
# ---------------------------------------------------------

async def _scrape_new_channel(
    page,
    channel: dict,
) -> tuple[int, int]:
    """
    اسکرپ اولیه کانال.

    فقط INITIAL_MESSAGES_LIMIT پیام آخر را می‌گیرد.

    مثلاً:
        INITIAL_MESSAGES_LIMIT = 50

    یعنی:
        50 پیام جدید/آخر کانال
    """

    title = channel["عنوان کانال"]

    print(
        f"[BALE][NEW] "
        f"channel={title} "
        f"target={INITIAL_MESSAGES_LIMIT}"
    )

    await _scroll_to_bottom(page)

    collected_ids: set[str] = set()

    total_saved = 0

    max_date_seen = None

    previous_oldest = None
    stable_scrolls = 0

    scroll_count = 0

    while len(collected_ids) < INITIAL_MESSAGES_LIMIT:

        scroll_count += 1

        if scroll_count > MAX_HISTORY_SCROLLS:

            print(
                f"[BALE][WARNING] "
                f"MAX_HISTORY_SCROLLS={MAX_HISTORY_SCROLLS} "
                f"reached for new channel {title}"
            )

            break

        before_count = len(collected_ids)

        batch_saved, batch_max_date = (
            await _collect_current_messages(
                page=page,
                channel=channel,
                last_scraped_date=None,
                collected_ids=collected_ids,
            )
        )

        total_saved += batch_saved

        if batch_max_date is not None:

            if max_date_seen is None:
                max_date_seen = batch_max_date
            else:
                max_date_seen = max(
                    max_date_seen,
                    batch_max_date,
                )

        oldest = await _get_oldest_rendered_date(page)

        print(
            f"[BALE][NEW] "
            f"channel={title} "
            f"scroll={scroll_count} "
            f"batch_saved={batch_saved} "
            f"collected={len(collected_ids)}/"
            f"{INITIAL_MESSAGES_LIMIT} "
            f"oldest={oldest or 0} "
            f"max_date={max_date_seen or 0}"
        )

        # -------------------------------------------------
        # آیا 50 پیام جمع شد؟
        # -------------------------------------------------

        if len(collected_ids) >= INITIAL_MESSAGES_LIMIT:

            print(
                f"[BALE][NEW] "
                f"هدف {INITIAL_MESSAGES_LIMIT} پیام رسید."
            )

            break

        # -------------------------------------------------
        # scroll به سمت پیام‌های قدیمی‌تر
        # -------------------------------------------------

        before_oldest = oldest

        ok = await _scroll_messages(
            page,
            "up",
        )

        if not ok:
            raise RuntimeError(
                "container پیام‌های Bale پیدا نشد."
            )

        await page.wait_for_timeout(
            SCROLL_WAIT_MS
        )

        after_oldest = await _get_oldest_rendered_date(page)

        # -------------------------------------------------
        # اگر oldest تغییر نکرد
        # -------------------------------------------------

        if after_oldest == before_oldest:

            stable_scrolls += 1

        else:

            stable_scrolls = 0

        # اگر چند بار هیچ پیام قدیمی‌تری نیامد،
        # احتمالاً به ابتدای تاریخچه رسیده‌ایم.
        if stable_scrolls >= 3:

            print(
                f"[BALE][NEW] "
                f"احتمالاً به ابتدای تاریخچه رسیدیم."
            )

            break

        # جلوگیری از loop در صورتی که هیچ پیام جدیدی وارد DOM نشود
        if len(collected_ids) == before_count:

            print(
                f"[BALE][NEW] "
                f"scroll پیام جدیدی به DOM اضافه نکرد."
            )

    # -----------------------------------------------------
    # برای cursor همیشه جدیدترین پیام را پیدا می‌کنیم
    # -----------------------------------------------------

    newest_date = await _get_newest_rendered_date(page)

    if newest_date is not None:

        max_date_seen = max(
            max_date_seen or 0,
            newest_date,
        )

    # -----------------------------------------------------
    # اگر هیچ پیام معتبر پیدا نشد => failure
    # -----------------------------------------------------

    if max_date_seen is None:

        raise RuntimeError(
            "هیچ پیام معتبری برای کانال جدید پیدا نشد."
        )

    print(
        f"[BALE][NEW][SUCCESS] "
        f"channel={title} "
        f"collected={len(collected_ids)} "
        f"saved={total_saved} "
        f"cursor={max_date_seen}"
    )

    return total_saved, max_date_seen


# ---------------------------------------------------------
# EXISTING CHANNEL
# ---------------------------------------------------------

async def _scrape_existing_channel(
    page,
    channel: dict,
    last_scraped_date: int,
) -> tuple[int, int]:
    """
    اسکرپ کانالی که قبلاً cursor دارد.

    از آخر کانال شروع می‌کنیم و به سمت بالا می‌رویم
    تا به last_scraped_date برسیم.
    """

    title = channel["عنوان کانال"]

    print(
        f"[BALE][EXISTING] "
        f"channel={title} "
        f"cursor={last_scraped_date}"
    )

    await _scroll_to_bottom(page)

    collected_ids: set[str] = set()

    total_saved = 0

    max_date_seen = last_scraped_date

    scroll_count = 0

    stable_scrolls = 0

    reached_cursor = False

    while not reached_cursor:

        scroll_count += 1

        if scroll_count > MAX_HISTORY_SCROLLS:

            raise RuntimeError(
                "تعداد مجاز scroll برای رسیدن به "
                "last_scraped_date تمام شد."
            )

        # -------------------------------------------------
        # بررسی پیام‌های فعلی
        # -------------------------------------------------

        messages = page.locator(MESSAGE_SELECTOR)

        count = await messages.count()

        batch_saved = 0

        for i in range(count):

            message = messages.nth(i)

            msg_sid = await message.get_attribute(
                "data-sid"
            )

            msg_date_raw = await message.get_attribute(
                "data-date"
            )

            msg_date = None

            if msg_date_raw:

                try:

                    parsed_date = int(msg_date_raw)

                    if parsed_date > 0:
                        msg_date = parsed_date

                except (TypeError, ValueError):

                    msg_date = None

            # -------------------------------------------------
            # اگر به cursor رسیدیم
            # -------------------------------------------------

            if (
                msg_date is not None
                and msg_date <= last_scraped_date
            ):

                reached_cursor = True

                continue

            # -------------------------------------------------
            # تاریخ جدید
            # -------------------------------------------------

            if msg_date is not None:

                max_date_seen = max(
                    max_date_seen,
                    msg_date,
                )

            unique_id = msg_sid or (
                f"date:{msg_date}"
                if msg_date is not None
                else f"index:{i}"
            )

            if unique_id in collected_ids:
                continue

            collected_ids.add(unique_id)

            # -------------------------------------------------
            # Parse
            # -------------------------------------------------

            try:

                parsed_news = await clean_body(
                    message,
                    channel_title=title,
                    channel_type=channel.get(
                        "نوع منبع",
                        "کانال بله",
                    ),
                )

            except Exception as e:

                _log_error(channel, e)

                print(
                    f"[BALE][PARSE_ERROR] "
                    f"channel={title} "
                    f"error={e}"
                )

                continue

            if (
                not parsed_news.get("عنوان")
                and not parsed_news.get("متن")
            ):
                continue

            # -------------------------------------------------
            # Save
            # -------------------------------------------------

            try:

                saved = save_news(parsed_news)

                if saved:
                    batch_saved += 1

            except Exception as e:

                _log_error(channel, e)

                print(
                    f"[BALE][SAVE_ERROR] "
                    f"channel={title} "
                    f"error={e}"
                )

        total_saved += batch_saved

        oldest = await _get_oldest_rendered_date(page)

        print(
            f"[BALE][EXISTING] "
            f"channel={title} "
            f"scroll={scroll_count} "
            f"batch_saved={batch_saved} "
            f"total_saved={total_saved} "
            f"oldest={oldest or 0} "
            f"cursor={last_scraped_date} "
            f"reached_cursor={reached_cursor}"
        )

        # -------------------------------------------------
        # اگر cursor پیدا شد تمام
        # -------------------------------------------------

        if reached_cursor:
            break

        # -------------------------------------------------
        # scroll به سمت بالا
        # -------------------------------------------------

        before_oldest = oldest

        ok = await _scroll_messages(
            page,
            "up",
        )

        if not ok:

            raise RuntimeError(
                "container پیام‌های Bale پیدا نشد."
            )

        await page.wait_for_timeout(
            SCROLL_WAIT_MS
        )

        after_oldest = await _get_oldest_rendered_date(page)

        if after_oldest == before_oldest:

            stable_scrolls += 1

        else:

            stable_scrolls = 0

        # -------------------------------------------------
        # اگر به انتهای تاریخچه رسیدیم
        # -------------------------------------------------

        if stable_scrolls >= 3:

            print(
                f"[BALE][EXISTING] "
                f"به انتهای تاریخچه رسیدیم "
                f"ولی cursor پیدا نشد."
            )

            # اگر تمام تاریخچه از cursor جدیدتر بوده،
            # این هم یک اجرای موفق محسوب می‌شود.
            break

    # -----------------------------------------------------
    # cursor جدید
    # -----------------------------------------------------

    newest_date = await _get_newest_rendered_date(page)

    if newest_date is not None:

        max_date_seen = max(
            max_date_seen,
            newest_date,
        )

    print(
        f"[BALE][EXISTING][SUCCESS] "
        f"channel={title} "
        f"saved={total_saved} "
        f"new_cursor={max_date_seen}"
    )

    return total_saved, max_date_seen


# ---------------------------------------------------------
# SINGLE CHANNEL
# ---------------------------------------------------------

async def _scrape_single_channel(
    page,
    channel: dict,
) -> tuple[int, int]:
    """
    تصمیم می‌گیرد کانال جدید است یا قبلاً scrape شده.
    """

    title = channel["عنوان کانال"]

    # -----------------------------------------------------
    # مهم:
    # فقط None یعنی کانال جدید.
    # 0 را هم به عنوان cursor معتبر در نظر نمی‌گیریم.
    # -----------------------------------------------------

    raw_cursor = channel.get("last_scraped_date")

    if raw_cursor is None:

        last_scraped_date = None

    else:

        try:

            last_scraped_date = int(raw_cursor)

            if last_scraped_date <= 0:
                last_scraped_date = None

        except (TypeError, ValueError):

            last_scraped_date = None

    is_new_channel = last_scraped_date is None

    print(
        f"[BALE][START] "
        f"channel={title} "
        f"last_scraped_date={last_scraped_date} "
        f"is_new_channel={is_new_channel}"
    )

    # -----------------------------------------------------
    # صفحه اصلی
    # -----------------------------------------------------

    await _ensure_channel_list_visible(page)

    dialog = page.locator(
        DIALOG_SELECTOR
    ).filter(
        has_text=title
    )

    if await dialog.count() == 0:

        raise RuntimeError(
            f"کانال «{title}» در لیست چت‌ها پیدا نشد"
        )

    await dialog.first.click()

    await page.wait_for_timeout(
        CHANNEL_LOAD_WAIT_MS
    )

    # -----------------------------------------------------
    # NEW
    # -----------------------------------------------------

    if is_new_channel:

        return await _scrape_new_channel(
            page,
            channel,
        )

    # -----------------------------------------------------
    # EXISTING
    # -----------------------------------------------------

    return await _scrape_existing_channel(
        page,
        channel,
        last_scraped_date,
    )


# ---------------------------------------------------------
# ALL CHANNELS
# ---------------------------------------------------------

async def scrape_all_channels() -> dict:
    """
    تمام کانال‌های فعال را scrape می‌کند.

    یک browser context مشترک استفاده می‌شود.
    """

    channels = get_active_channels()

    summary = {
        "success": [],
        "failed": [],
    }

    if not channels:

        return summary

    async with async_playwright() as p:

        context = await p.chromium.launch_persistent_context(
            user_data_dir="./profile",
            headless=headless,
        )

        page = (
            context.pages[0]
            if context.pages
            else await context.new_page()
        )

        await page.goto(BASE_URL)

        await page.wait_for_timeout(3000)

        for channel in channels:

            channel_id = channel["_id"]

            last_error: Exception | None = None

            for attempt in range(
                1,
                MAX_RETRIES_PER_CHANNEL + 1,
            ):

                print(
                    f"[BALE] "
                    f"channel={channel['عنوان کانال']} "
                    f"attempt={attempt}"
                )

                try:

                    saved, last_date = (
                        await _scrape_single_channel(
                            page,
                            channel,
                        )
                    )

                    # -------------------------------------------------
                    # فقط اجرای واقعاً موفق cursor را update می‌کند.
                    # -------------------------------------------------

                    mark_channel_scraped(
                        channel_id,
                        success=True,
                        last_message_date=last_date,
                    )

                    summary["success"].append(
                        {
                            "channel_id": channel_id,
                            "saved": saved,
                            "last_message_date": last_date,
                        }
                    )

                    print(
                        f"[BALE][SUCCESS] "
                        f"channel={channel['عنوان کانال']} "
                        f"saved={saved} "
                        f"last_message_date={last_date}"
                    )

                    last_error = None

                    break

                except Exception as e:

                    last_error = e

                    print(
                        f"[BALE][ERROR] "
                        f"channel={channel['عنوان کانال']} "
                        f"attempt={attempt} "
                        f"error={e}"
                    )

                    await page.wait_for_timeout(2000)

            # ---------------------------------------------------------
            # هر دو attempt شکست خورد
            # ---------------------------------------------------------

            if last_error is not None:

                _log_error(
                    channel,
                    last_error,
                )

                mark_channel_scraped(
                    channel_id,
                    success=False,
                )

                summary["failed"].append(
                    {
                        "channel_id": channel_id,
                        "error": str(last_error),
                    }
                )

        await context.close()

    return summary