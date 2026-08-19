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


# =========================================================
# Configuration
# =========================================================

headless = (
    os.getenv("PLAYWRIGHT_HEADLESS", "true").lower()
    == "true"
)

MAX_RETRIES_PER_CHANNEL = 2

# اولین scrape
INITIAL_MESSAGES_LIMIT = 50

# حداکثر scroll برای history
MAX_HISTORY_SCROLLS = 100

# مقدار حرکت به سمت پیام‌های قدیمی‌تر
SCROLL_STEP = 1200

# زمان انتظار lazy-load
SCROLL_WAIT_MS = 1200

# زمان انتظار بعد از باز شدن کانال
CHANNEL_LOAD_WAIT_MS = 2000

# چند بار باید واقعاً در ابتدای scroll بمانیم
# تا بگوییم به ابتدای history رسیده‌ایم.
TOP_STABLE_LIMIT = 5

# چند بار bottom باید تثبیت شود
BOTTOM_STABLE_LIMIT = 3

BASE_URL = "https://web.bale.ai"

DIALOG_SELECTOR = '[aria-label="dialog-item"]'
MESSAGE_SELECTOR = ".message-item"


# =========================================================
# Logging
# =========================================================

def _log_error(channel: dict, error: Exception) -> None:
    """
    ذخیره خطای scraper در MongoDB.
    """

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


# =========================================================
# Basic DOM helpers
# =========================================================

async def _ensure_channel_list_visible(page) -> None:
    """
    برگشت به صفحه اصلی Bale.
    """

    await page.goto(BASE_URL)

    await page.wait_for_selector(
        DIALOG_SELECTOR,
        timeout=15000,
    )


async def _get_message_dates(page) -> list[int]:
    """
    تمام data-date های معتبر پیام‌های فعلی DOM.
    """

    return await page.evaluate(
        """
        (selector) => {

            const elements =
                document.querySelectorAll(selector);

            return Array.from(elements)
                .map(el => Number(el.dataset.date))
                .filter(
                    date =>
                        Number.isFinite(date)
                        && date > 0
                );
        }
        """,
        MESSAGE_SELECTOR,
    )


async def _get_oldest_rendered_date(
    page,
) -> int | None:
    """
    قدیمی‌ترین data-date فعلی DOM.
    """

    dates = await _get_message_dates(page)

    if not dates:
        return None

    return min(dates)


async def _get_newest_rendered_date(
    page,
) -> int | None:
    """
    جدیدترین data-date فعلی DOM.
    """

    dates = await _get_message_dates(page)

    if not dates:
        return None

    return max(dates)


# =========================================================
# DOM Snapshot
# =========================================================

async def _get_message_snapshot(page) -> dict:
    """
    snapshot از وضعیت فعلی پیام‌ها.

    برای تشخیص virtual scrolling استفاده می‌شود.
    """

    return await page.evaluate(
        """
        (selector) => {

            const elements =
                Array.from(
                    document.querySelectorAll(selector)
                );

            const messages = elements.map(el => ({
                sid: el.dataset.sid || null,
                date: Number(el.dataset.date) || null
            }));

            const validDates = messages
                .map(x => x.date)
                .filter(
                    x =>
                        Number.isFinite(x)
                        && x > 0
                );

            return {
                count: messages.length,

                oldest:
                    validDates.length
                        ? Math.min(...validDates)
                        : null,

                newest:
                    validDates.length
                        ? Math.max(...validDates)
                        : null,

                firstSid:
                    messages.length
                        ? messages[0].sid
                        : null,

                lastSid:
                    messages.length
                        ? messages[messages.length - 1].sid
                        : null,

                sids:
                    messages
                        .map(x => x.sid)
                        .filter(Boolean)
            };
        }
        """,
        MESSAGE_SELECTOR,
    )


# =========================================================
# Scroll container
# =========================================================

async def _get_scroll_state(
    page,
) -> dict | None:
    """
    وضعیت واقعی scroll container پیام‌ها.
    """

    return await page.evaluate(
        """
        (messageSelector) => {

            const message =
                document.querySelector(
                    messageSelector
                );

            if (!message) {
                return null;
            }

            let container =
                message.parentElement;

            while (container) {

                const style =
                    window.getComputedStyle(
                        container
                    );

                const overflowY =
                    style.overflowY;

                const isScrollable =
                    (
                        overflowY === "auto" ||
                        overflowY === "scroll" ||
                        overflowY === "overlay"
                    )
                    &&
                    container.scrollHeight >
                    container.clientHeight + 5;

                if (isScrollable) {

                    const maxScrollTop =
                        Math.max(
                            0,
                            container.scrollHeight -
                            container.clientHeight
                        );

                    return {
                        scrollTop:
                            container.scrollTop,

                        scrollHeight:
                            container.scrollHeight,

                        clientHeight:
                            container.clientHeight,

                        maxScrollTop:
                            maxScrollTop,

                        distanceFromBottom:
                            Math.max(
                                0,
                                maxScrollTop -
                                container.scrollTop
                            ),

                        distanceFromTop:
                            Math.max(
                                0,
                                container.scrollTop
                            )
                    };
                }

                container =
                    container.parentElement;
            }

            const fallback =
                document.scrollingElement ||
                document.documentElement;

            const maxScrollTop =
                Math.max(
                    0,
                    fallback.scrollHeight -
                    fallback.clientHeight
                );

            return {
                scrollTop:
                    fallback.scrollTop,

                scrollHeight:
                    fallback.scrollHeight,

                clientHeight:
                    fallback.clientHeight,

                maxScrollTop:
                    maxScrollTop,

                distanceFromBottom:
                    Math.max(
                        0,
                        maxScrollTop -
                        fallback.scrollTop
                    ),

                distanceFromTop:
                    Math.max(
                        0,
                        fallback.scrollTop
                    )
            };
        }
        """,
        MESSAGE_SELECTOR,
    )


# =========================================================
# Scroll down
# =========================================================

async def _force_scroll_bottom(page) -> bool:
    """
    یک بار container را مستقیم به انتها می‌برد.
    """

    result = await page.evaluate(
        """
        (messageSelector) => {

            const message =
                document.querySelector(
                    messageSelector
                );

            if (!message) {
                return false;
            }

            let container =
                message.parentElement;

            while (container) {

                const style =
                    window.getComputedStyle(
                        container
                    );

                const overflowY =
                    style.overflowY;

                const isScrollable =
                    (
                        overflowY === "auto" ||
                        overflowY === "scroll" ||
                        overflowY === "overlay"
                    )
                    &&
                    container.scrollHeight >
                    container.clientHeight + 5;

                if (isScrollable) {

                    container.scrollTop =
                        container.scrollHeight;

                    return true;
                }

                container =
                    container.parentElement;
            }

            const fallback =
                document.scrollingElement ||
                document.documentElement;

            fallback.scrollTop =
                fallback.scrollHeight;

            return true;
        }
        """,
        MESSAGE_SELECTOR,
    )

    return bool(result)


async def _scroll_to_bottom(page) -> None:
    """
    رفتن قطعی به انتهای کانال.

    چون Bale lazy-load دارد، بعد از رسیدن به bottom
    چند بار دیگر وضعیت بررسی می‌شود.
    """

    print(
        "[BALE][BOTTOM] "
        "شروع رفتن به انتهای کانال..."
    )

    stable_bottom_count = 0

    for attempt in range(1, 21):

        state = await _get_scroll_state(page)

        if state is None:

            raise RuntimeError(
                "container پیام‌های Bale پیدا نشد."
            )

        print(
            f"[BALE][BOTTOM] "
            f"attempt={attempt} "
            f"scrollTop="
            f"{state['scrollTop']:.0f} "
            f"max="
            f"{state['maxScrollTop']:.0f} "
            f"height="
            f"{state['scrollHeight']:.0f}"
        )

        await _force_scroll_bottom(page)

        await page.wait_for_timeout(
            SCROLL_WAIT_MS
        )

        await page.wait_for_timeout(500)

        state = await _get_scroll_state(page)

        if state is None:
            continue

        distance = (
            state["distanceFromBottom"]
        )

        print(
            f"[BALE][BOTTOM] "
            f"after_scrollTop="
            f"{state['scrollTop']:.0f} "
            f"max="
            f"{state['maxScrollTop']:.0f} "
            f"distance="
            f"{distance:.0f}"
        )

        if distance <= 5:

            stable_bottom_count += 1

            print(
                f"[BALE][BOTTOM] "
                f"bottom confirmed "
                f"{stable_bottom_count}/"
                f"{BOTTOM_STABLE_LIMIT}"
            )

        else:

            stable_bottom_count = 0

        if (
            stable_bottom_count
            >= BOTTOM_STABLE_LIMIT
        ):
            break

    snapshot = await _get_message_snapshot(page)

    print(
        f"[BALE][BOTTOM][SUCCESS] "
        f"messages={snapshot['count']} "
        f"oldest={snapshot['oldest'] or 0} "
        f"newest={snapshot['newest'] or 0}"
    )


# =========================================================
# Scroll up
# =========================================================

async def _scroll_messages_up(
    page,
) -> dict:
    """
    یک مرحله به سمت پیام‌های قدیمی‌تر می‌رود.

    علاوه بر scrollTop، snapshot قبل و بعد
    را برمی‌گرداند.
    """

    before_state = (
        await _get_scroll_state(page)
    )

    before_snapshot = (
        await _get_message_snapshot(page)
    )

    result = await page.evaluate(
        """
        ({messageSelector, step}) => {

            const message =
                document.querySelector(
                    messageSelector
                );

            if (!message) {
                return {
                    ok: false,
                    reason: "message-not-found"
                };
            }

            let container =
                message.parentElement;

            while (container) {

                const style =
                    window.getComputedStyle(
                        container
                    );

                const overflowY =
                    style.overflowY;

                const isScrollable =
                    (
                        overflowY === "auto" ||
                        overflowY === "scroll" ||
                        overflowY === "overlay"
                    )
                    &&
                    container.scrollHeight >
                    container.clientHeight + 5;

                if (isScrollable) {

                    const before =
                        container.scrollTop;

                    container.scrollBy({
                        top: -step,
                        behavior: "instant"
                    });

                    const after =
                        container.scrollTop;

                    return {
                        ok: true,
                        before,
                        after,
                        maxScrollTop:
                            Math.max(
                                0,
                                container.scrollHeight -
                                container.clientHeight
                            ),
                        scrollHeight:
                            container.scrollHeight
                    };
                }

                container =
                    container.parentElement;
            }

            return {
                ok: false,
                reason:
                    "scroll-container-not-found"
            };
        }
        """,
        {
            "messageSelector": MESSAGE_SELECTOR,
            "step": SCROLL_STEP,
        },
    )

    if not result.get("ok"):

        raise RuntimeError(
            "container پیام‌های Bale "
            "پیدا نشد."
        )

    await page.wait_for_timeout(
        SCROLL_WAIT_MS
    )

    await page.wait_for_timeout(300)

    after_state = (
        await _get_scroll_state(page)
    )

    after_snapshot = (
        await _get_message_snapshot(page)
    )

    return {
        "before_state": before_state,
        "after_state": after_state,
        "before_snapshot":
            before_snapshot,
        "after_snapshot":
            after_snapshot,
        "scroll_result": result,
    }


# =========================================================
# Detect history progress
# =========================================================

def _history_progressed(
    result: dict,
) -> bool:
    """
    مشخص می‌کند آیا scroll به سمت history
    واقعاً پیشرفت کرده یا نه.

    در virtual DOM نباید فقط oldest را بررسی کنیم.

    هر کدام از این‌ها می‌تواند نشانه progress باشد:

        scrollTop تغییر کرده
        scrollHeight تغییر کرده
        firstSid تغییر کرده
        lastSid تغییر کرده
        oldest تغییر کرده
        newest تغییر کرده
        SID جدید وارد DOM شده
    """

    before_state = result["before_state"]
    after_state = result["after_state"]

    before_snapshot = result[
        "before_snapshot"
    ]

    after_snapshot = result[
        "after_snapshot"
    ]

    if before_state is None or after_state is None:
        return False

    # -----------------------------------------------------
    # scrollTop
    # -----------------------------------------------------

    if (
        after_state["scrollTop"]
        < before_state["scrollTop"] - 2
    ):
        return True

    # -----------------------------------------------------
    # scrollHeight
    # -----------------------------------------------------

    if (
        after_state["scrollHeight"]
        != before_state["scrollHeight"]
    ):
        return True

    # -----------------------------------------------------
    # oldest
    # -----------------------------------------------------

    if (
        after_snapshot["oldest"]
        != before_snapshot["oldest"]
    ):
        return True

    # -----------------------------------------------------
    # newest
    # -----------------------------------------------------

    if (
        after_snapshot["newest"]
        != before_snapshot["newest"]
    ):
        return True

    # -----------------------------------------------------
    # first SID
    # -----------------------------------------------------

    if (
        after_snapshot["firstSid"]
        != before_snapshot["firstSid"]
    ):
        return True

    # -----------------------------------------------------
    # last SID
    # -----------------------------------------------------

    if (
        after_snapshot["lastSid"]
        != before_snapshot["lastSid"]
    ):
        return True

    # -----------------------------------------------------
    # SID set
    # -----------------------------------------------------

    before_sids = set(
        before_snapshot["sids"]
    )

    after_sids = set(
        after_snapshot["sids"]
    )

    if before_sids != after_sids:
        return True

    return False


# =========================================================
# Message collection
# =========================================================

async def _collect_current_messages(
    page,
    channel: dict,
    last_scraped_date: int | None,
    collected_ids: set[str],
) -> tuple[int, int | None, bool]:
    """
    پیام‌های فعلی DOM را بررسی و ذخیره می‌کند.

    خروجی:

        saved_count
        max_date_seen
        cursor_found
    """

    title = channel["عنوان کانال"]

    messages = page.locator(
        MESSAGE_SELECTOR
    )

    count = await messages.count()

    saved_count = 0

    max_date_seen = None

    cursor_found = False

    for i in range(count):

        message = messages.nth(i)

        msg_sid = (
            await message.get_attribute(
                "data-sid"
            )
        )

        msg_date_raw = (
            await message.get_attribute(
                "data-date"
            )
        )

        msg_date = None

        if msg_date_raw:

            try:

                parsed_date = int(
                    msg_date_raw
                )

                if parsed_date > 0:
                    msg_date = parsed_date

            except (
                TypeError,
                ValueError,
            ):

                msg_date = None

        # -------------------------------------------------
        # Cursor
        # -------------------------------------------------

        if (
            last_scraped_date is not None
            and msg_date is not None
            and msg_date <= last_scraped_date
        ):

            cursor_found = True

            continue

        # -------------------------------------------------
        # max date
        # -------------------------------------------------

        if msg_date is not None:

            if max_date_seen is None:

                max_date_seen = msg_date

            else:

                max_date_seen = max(
                    max_date_seen,
                    msg_date,
                )

        # -------------------------------------------------
        # unique ID
        # -------------------------------------------------

        unique_id = (
            msg_sid
            or (
                f"date:{msg_date}"
                if msg_date is not None
                else f"index:{i}"
            )
        )

        if unique_id in collected_ids:
            continue

        collected_ids.add(
            unique_id
        )

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

            _log_error(
                channel,
                e,
            )

            print(
                f"[BALE][PARSE_ERROR] "
                f"channel={title} "
                f"index={i} "
                f"error={e}"
            )

            continue

        # -------------------------------------------------
        # Empty
        # -------------------------------------------------

        if (
            not parsed_news.get("عنوان")
            and not parsed_news.get("متن")
        ):
            continue

        # -------------------------------------------------
        # Save
        # -------------------------------------------------

        try:

            saved = save_news(
                parsed_news
            )

            if saved:
                saved_count += 1

        except Exception as e:

            _log_error(
                channel,
                e,
            )

            print(
                f"[BALE][SAVE_ERROR] "
                f"channel={title} "
                f"error={e}"
            )

    return (
        saved_count,
        max_date_seen,
        cursor_found,
    )


# =========================================================
# NEW CHANNEL
# =========================================================

async def _scrape_new_channel(
    page,
    channel: dict,
) -> tuple[int, int]:
    """
    اولین scrape کانال.

    آخرین INITIAL_MESSAGES_LIMIT پیام را می‌گیرد.
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

    scroll_count = 0

    top_stable_count = 0

    while (
        len(collected_ids)
        < INITIAL_MESSAGES_LIMIT
    ):

        scroll_count += 1

        if (
            scroll_count
            > MAX_HISTORY_SCROLLS
        ):

            print(
                f"[BALE][NEW][WARNING] "
                f"MAX_HISTORY_SCROLLS "
                f"reached."
            )

            break

        before_count = len(
            collected_ids
        )

        (
            batch_saved,
            batch_max_date,
            _,
        ) = await _collect_current_messages(
            page=page,
            channel=channel,
            last_scraped_date=None,
            collected_ids=collected_ids,
        )

        total_saved += batch_saved

        if batch_max_date is not None:

            if max_date_seen is None:

                max_date_seen = (
                    batch_max_date
                )

            else:

                max_date_seen = max(
                    max_date_seen,
                    batch_max_date,
                )

        snapshot = (
            await _get_message_snapshot(
                page
            )
        )

        print(
            f"[BALE][NEW] "
            f"channel={title} "
            f"scroll={scroll_count} "
            f"batch_saved={batch_saved} "
            f"collected="
            f"{len(collected_ids)}/"
            f"{INITIAL_MESSAGES_LIMIT} "
            f"oldest="
            f"{snapshot['oldest'] or 0} "
            f"newest="
            f"{snapshot['newest'] or 0}"
        )

        # -------------------------------------------------
        # هدف رسید
        # -------------------------------------------------

        if (
            len(collected_ids)
            >= INITIAL_MESSAGES_LIMIT
        ):

            break

        # -------------------------------------------------
        # Scroll UP
        # -------------------------------------------------

        result = (
            await _scroll_messages_up(
                page
            )
        )

        progressed = _history_progressed(
            result
        )

        after_snapshot = result[
            "after_snapshot"
        ]

        after_state = result[
            "after_state"
        ]

        print(
            f"[BALE][NEW][SCROLL] "
            f"scrollTop="
            f"{after_state['scrollTop']:.0f} "
            f"height="
            f"{after_state['scrollHeight']:.0f} "
            f"oldest="
            f"{after_snapshot['oldest'] or 0} "
            f"newest="
            f"{after_snapshot['newest'] or 0} "
            f"progressed={progressed}"
        )

        # -------------------------------------------------
        # تشخیص ابتدای واقعی
        # -------------------------------------------------

        if progressed:

            top_stable_count = 0

        else:

            top_stable_count += 1

        if (
            top_stable_count
            >= TOP_STABLE_LIMIT
        ):

            state = (
                await _get_scroll_state(
                    page
                )
            )

            if (
                state is not None
                and state["distanceFromTop"]
                <= 5
            ):

                print(
                    "[BALE][NEW] "
                    "به ابتدای واقعی "
                    "تاریخچه رسیدیم."
                )

                break

        # -------------------------------------------------
        # هیچ پیام جدیدی جمع نشد
        # -------------------------------------------------

        if (
            len(collected_ids)
            == before_count
            and not progressed
        ):

            print(
                "[BALE][NEW] "
                "هیچ progress جدیدی "
                "دیده نشد."
            )

    # -----------------------------------------------------
    # Cursor
    # -----------------------------------------------------

    newest_date = (
        await _get_newest_rendered_date(
            page
        )
    )

    if newest_date is not None:

        max_date_seen = max(
            max_date_seen or 0,
            newest_date,
        )

    if max_date_seen is None:

        raise RuntimeError(
            "هیچ پیام معتبری برای "
            "کانال جدید پیدا نشد."
        )

    print(
        f"[BALE][NEW][SUCCESS] "
        f"channel={title} "
        f"collected="
        f"{len(collected_ids)} "
        f"saved={total_saved} "
        f"cursor={max_date_seen}"
    )

    return (
        total_saved,
        max_date_seen,
    )


# =========================================================
# EXISTING CHANNEL
# =========================================================

async def _scrape_existing_channel(
    page,
    channel: dict,
    last_scraped_date: int,
) -> tuple[int, int]:
    """
    scrape کانال موجود.

    مهم:

    cursor قبلی باید واقعاً در DOM دیده شود.

    اگر cursor پیدا نشود، تابع موفق محسوب نمی‌شود
    و cursor جدید به MongoDB داده نمی‌شود.
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

    no_progress_count = 0

    cursor_found = False

    while not cursor_found:

        scroll_count += 1

        if (
            scroll_count
            > MAX_HISTORY_SCROLLS
        ):

            raise RuntimeError(
                "MAX_HISTORY_SCROLLS رسید "
                "ولی cursor پیدا نشد."
            )

        # -------------------------------------------------
        # Snapshot قبل
        # -------------------------------------------------

        before_snapshot = (
            await _get_message_snapshot(
                page
            )
        )

        # -------------------------------------------------
        # Collect
        # -------------------------------------------------

        (
            batch_saved,
            batch_max_date,
            found,
        ) = await _collect_current_messages(
            page=page,
            channel=channel,
            last_scraped_date=
                last_scraped_date,
            collected_ids=collected_ids,
        )

        total_saved += batch_saved

        if batch_max_date is not None:

            max_date_seen = max(
                max_date_seen,
                batch_max_date,
            )

        if found:

            cursor_found = True

            print(
                f"[BALE][EXISTING] "
                f"cursor پیدا شد."
            )

        # -------------------------------------------------
        # Snapshot بعد collect
        # -------------------------------------------------

        snapshot = (
            await _get_message_snapshot(
                page
            )
        )

        state = (
            await _get_scroll_state(
                page
            )
        )

        print(
            f"[BALE][EXISTING] "
            f"scroll={scroll_count} "
            f"batch_saved={batch_saved} "
            f"total_saved={total_saved} "
            f"DOM={snapshot['count']} "
            f"oldest="
            f"{snapshot['oldest'] or 0} "
            f"newest="
            f"{snapshot['newest'] or 0} "
            f"cursor="
            f"{last_scraped_date} "
            f"reached_cursor="
            f"{cursor_found}"
        )

        # -------------------------------------------------
        # Cursor پیدا شد
        # -------------------------------------------------

        if cursor_found:

            break

        # -------------------------------------------------
        # بررسی اینکه در بالای واقعی هستیم
        # -------------------------------------------------

        if (
            state is not None
            and state["distanceFromTop"]
            <= 5
        ):

            raise RuntimeError(
                "به ابتدای واقعی تاریخچه رسیدیم "
                "ولی last_scraped_date پیدا نشد."
            )

        # -------------------------------------------------
        # Scroll UP
        # -------------------------------------------------

        result = (
            await _scroll_messages_up(
                page
            )
        )

        progressed = _history_progressed(
            result
        )

        after_state = result[
            "after_state"
        ]

        after_snapshot = result[
            "after_snapshot"
        ]

        print(
            f"[BALE][EXISTING][SCROLL] "
            f"beforeTop="
            f"{result['before_state']['scrollTop']:.0f} "
            f"afterTop="
            f"{after_state['scrollTop']:.0f} "
            f"height="
            f"{after_state['scrollHeight']:.0f} "
            f"oldest="
            f"{after_snapshot['oldest'] or 0} "
            f"newest="
            f"{after_snapshot['newest'] or 0} "
            f"progressed="
            f"{progressed}"
        )

        # -------------------------------------------------
        # Progress
        # -------------------------------------------------

        if progressed:

            no_progress_count = 0

        else:

            no_progress_count += 1

        # -------------------------------------------------
        # اگر چند بار هیچ progress نبود
        # -------------------------------------------------

        if (
            no_progress_count
            >= TOP_STABLE_LIMIT
        ):

            state = (
                await _get_scroll_state(
                    page
                )
            )

            if (
                state is not None
                and state["distanceFromTop"]
                <= 5
            ):

                raise RuntimeError(
                    "به ابتدای تاریخچه رسیدیم "
                    "ولی cursor پیدا نشد."
                )

    # =====================================================
    # فقط در صورت پیدا شدن cursor
    # =====================================================

    if not cursor_found:

        raise RuntimeError(
            "cursor پیدا نشد."
        )

    # -----------------------------------------------------
    # جدیدترین تاریخ
    # -----------------------------------------------------

    newest_date = (
        await _get_newest_rendered_date(
            page
        )
    )

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

    return (
        total_saved,
        max_date_seen,
    )


# =========================================================
# SINGLE CHANNEL
# =========================================================

async def _scrape_single_channel(
    page,
    channel: dict,
) -> tuple[int, int]:
    """
    تعیین می‌کند کانال جدید است
    یا existing.
    """

    title = channel["عنوان کانال"]

    raw_cursor = channel.get(
        "last_scraped_date"
    )

    if raw_cursor is None:

        last_scraped_date = None

    else:

        try:

            last_scraped_date = int(
                raw_cursor
            )

            if last_scraped_date <= 0:
                last_scraped_date = None

        except (
            TypeError,
            ValueError,
        ):

            last_scraped_date = None

    is_new_channel = (
        last_scraped_date is None
    )

    print(
        f"[BALE][START] "
        f"channel={title} "
        f"last_scraped_date="
        f"{last_scraped_date} "
        f"is_new_channel="
        f"{is_new_channel}"
    )

    # -----------------------------------------------------
    # Channel list
    # -----------------------------------------------------

    await _ensure_channel_list_visible(
        page
    )

    dialog = page.locator(
        DIALOG_SELECTOR
    ).filter(
        has_text=title
    )

    if await dialog.count() == 0:

        raise RuntimeError(
            f"کانال «{title}» "
            f"در لیست چت‌ها پیدا نشد."
        )

    await dialog.first.click()

    await page.wait_for_timeout(
        CHANNEL_LOAD_WAIT_MS
    )

    # -----------------------------------------------------
    # New
    # -----------------------------------------------------

    if is_new_channel:

        return await _scrape_new_channel(
            page,
            channel,
        )

    # -----------------------------------------------------
    # Existing
    # -----------------------------------------------------

    return await _scrape_existing_channel(
        page,
        channel,
        last_scraped_date,
    )


# =========================================================
# ALL CHANNELS
# =========================================================

async def scrape_all_channels() -> dict:
    """
    scrape تمام کانال‌های فعال.
    """

    channels = get_active_channels()

    summary = {
        "success": [],
        "failed": [],
    }

    if not channels:

        return summary

    async with async_playwright() as p:

        context = (
            await p.chromium.launch_persistent_context(
                user_data_dir="./profile",
                headless=headless,
            )
        )

        page = (
            context.pages[0]
            if context.pages
            else await context.new_page()
        )

        await page.goto(
            BASE_URL
        )

        await page.wait_for_timeout(
            3000
        )

        # =================================================
        # Channels
        # =================================================

        for channel in channels:

            channel_id = channel["_id"]

            last_error: Exception | None = None

            for attempt in range(
                1,
                MAX_RETRIES_PER_CHANNEL + 1,
            ):

                print(
                    f"[BALE] "
                    f"channel="
                    f"{channel['عنوان کانال']} "
                    f"attempt={attempt}"
                )

                try:

                    (
                        saved,
                        last_date,
                    ) = await _scrape_single_channel(
                        page,
                        channel,
                    )

                    # -------------------------------------------------
                    # فقط اجرای واقعاً موفق cursor را update می‌کند
                    # -------------------------------------------------

                    mark_channel_scraped(
                        channel_id,
                        success=True,
                        last_message_date=
                            last_date,
                    )

                    summary["success"].append(
                        {
                            "channel_id":
                                channel_id,
                            "saved":
                                saved,
                            "last_message_date":
                                last_date,
                        }
                    )

                    print(
                        f"[BALE][SUCCESS] "
                        f"channel="
                        f"{channel['عنوان کانال']} "
                        f"saved={saved} "
                        f"last_message_date="
                        f"{last_date}"
                    )

                    last_error = None

                    break

                except Exception as e:

                    last_error = e

                    print(
                        f"[BALE][ERROR] "
                        f"channel="
                        f"{channel['عنوان کانال']} "
                        f"attempt={attempt} "
                        f"error={e}"
                    )

                    await page.wait_for_timeout(
                        2000
                    )

            # ---------------------------------------------------------
            # همه تلاش‌ها شکست خورد
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
                        "channel_id":
                            channel_id,
                        "error":
                            str(last_error),
                    }
                )

        await context.close()

    return summary