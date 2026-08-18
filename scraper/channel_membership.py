import logging
import os
from pathlib import Path

from playwright.sync_api import Locator, sync_playwright

logging.basicConfig(
    level=logging.DEBUG if os.getenv("DEBUG") else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

log = logging.getLogger("join_bale")

headless = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() == "true"

debug_dir = Path("./debug")


def _dump_debug_info(page, step: str) -> None:
    """موقع خطا، اسکرین‌شات و HTML صفحه رو برای دیباگ ذخیره می‌کنه."""

    debug_dir.mkdir(exist_ok=True)

    safe_step = step.replace(" ", "_")

    screenshot_path = debug_dir / f"{safe_step}.png"
    html_path = debug_dir / f"{safe_step}.html"

    try:
        page.screenshot(
            path=str(screenshot_path),
            full_page=True,
        )

        html_path.write_text(
            page.content(),
            encoding="utf-8",
        )

        log.error(
            "دیباگ ذخیره شد: %s و %s",
            screenshot_path,
            html_path,
        )

    except Exception:
        log.exception(
            "حتی ذخیره‌ی اطلاعات دیباگ هم شکست خورد"
        )


def _click_through_ripple(
    locator: Locator,
    step: str,
) -> None:

    log.debug(
        "در حال کلیک: %s",
        step,
    )

    locator.wait_for(
        state="visible",
        timeout=30000,
    )

    locator.click(
        force=True,
        timeout=30000,
    )

    log.debug(
        "کلیک انجام شد: %s",
        step,
    )


def join_channel_in_bale(
    channel_id: str,
) -> bool:

    with sync_playwright() as p:

        context = p.chromium.launch_persistent_context(
            user_data_dir="./profile",
            headless=headless,
            slow_mo=200 if os.getenv("DEBUG") else 0,
        )

        page = (
            context.pages[0]
            if context.pages
            else context.new_page()
        )

        # لاگ‌های مرورگر
        page.on(
            "console",
            lambda msg: log.debug(
                "[browser console] %s",
                msg.text,
            ),
        )

        page.on(
            "pageerror",
            lambda err: log.error(
                "[page error] %s",
                err,
            ),
        )

        current_step = "goto"

        try:

            # --------------------------------
            # 1. باز کردن Bale
            # --------------------------------

            log.info(
                "در حال باز کردن web.bale.ai"
            )

            page.goto(
                "https://web.bale.ai",
                wait_until="domcontentloaded",
            )
            # --------------------------------
            # 2. Search
            # --------------------------------

            current_step = "open_search"

            search_input = page.locator(
                'input[type="search"]'
            )

            if (
                search_input.count() == 0
                or not search_input.first.is_visible()
            ):

                log.info(
                    "سرچ‌باکس بسته است، "
                    "در حال کلیک روی Search"
                )

                search_icon = page.locator(
                    '[aria-label="Search-icon"]'
                ).first
                search_icon.wait_for(
                    state="visible",
                    timeout=30000,
                )
                # parent همان container قابل کلیک است
                search_button = search_icon.locator(
                    "xpath=.."
                )

                _click_through_ripple(
                    search_button,
                    current_step,
                )

            else:

                log.info(
                    "سرچ‌باکس از قبل باز است"
                )
            # --------------------------------
            # 3. صبر برای Search Input
            # --------------------------------

            current_step = "wait_search_input"

            search_input.wait_for(
                state="visible",
                timeout=30000,
            )
            # --------------------------------
            # 4. انتخاب تب کانال
            # --------------------------------

            current_step = "select_channel_tab"

            log.info(
                "در حال انتخاب تب کانال"
            )

            channel_tab = page.locator(
                "#channel"
            )

            _click_through_ripple(
                channel_tab,
                current_step,
            )

            # --------------------------------
            # 5. وارد کردن آیدی
            # --------------------------------

            current_step = "fill_search"

            log.info(
                "در حال جستجوی کانال: %s",
                channel_id,
            )
            search_input.fill(
                channel_id
            )

            # --------------------------------
            # 6. پیدا کردن نتیجه
            # --------------------------------

            current_step = "wait_for_result"

            bale_id = channel_id.lstrip("@")

            log.info(
                "منتظر نتیجه حاوی: %s",
                bale_id,
            )

            result = (
                page.locator("[data-item-index]")
                .filter(has_text=bale_id)
                .first
            )
            result.wait_for(
                state="visible",
                timeout=30000,
            )

            # --------------------------------
            # 7. Join
            # --------------------------------

            current_step = "click_join"

            join_button = result.locator(
                'button[aria-label="عضویت"]'
            )
            if join_button.count() > 0:

                log.info(
                    "دکمه عضویت پیدا شد"
                )

                _click_through_ripple(
                    join_button,
                    current_step,
                )
                # کمی فرصت بدهیم تا وضعیت UI تغییر کند
                page.wait_for_timeout(1500)

            else:

                log.info(
                    "دکمه عضویت وجود ندارد؛ "
                    "احتمالاً قبلاً عضو هستیم"
                )

            log.info(
                "عضویت در %s موفق بود",
                channel_id,
            )

            return True

        except Exception:

            log.exception(
                "خطا در مرحله: %s",
                current_step,
            )

            _dump_debug_info(
                page,
                current_step,
            )
            raise

        finally:

            context.close()