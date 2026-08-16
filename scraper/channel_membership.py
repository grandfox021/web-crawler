import os

from playwright.sync_api import sync_playwright

headless = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() == "true"


def join_channel_in_bale(channel_id: str) -> bool:
    """با استفاده از سرچ داخل بله، کانال رو پیدا و عضوش می‌شه.

    channel_id مثلا "@iribnews".
    اگه از قبل عضو باشیم یا دکمه‌ی عضویت پیدا نشه، موفقیت‌آمیز در نظر گرفته می‌شه.
    اگه اصلا نتیجه‌ای تو سرچ پیدا نشه، خطا می‌ده.
    """

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir="./profile",
            headless=headless,
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://web.bale.ai")
        page.wait_for_timeout(3000)

        # ۱. کلیک روی آیکون جستجو
        page.locator('[aria-label="Search-icon"]').click()
        page.wait_for_timeout(1000)

        # ۲. کلیک روی تب «کانال»
        page.locator("#channel").click()
        page.wait_for_timeout(1000)

        # ۳. تایپ آیدی کانال در سرچ
        search_input = page.locator('input[placeholder="جستجوی کانال"]')
        search_input.fill(channel_id)
        page.wait_for_timeout(2000)

        # ۴. اولین نتیجه‌ای که شامل این آیدیه رو پیدا کن
        bare_id = channel_id.lstrip("@")
        result = page.locator("[data-item-index]").filter(has_text=bare_id).first

        if result.count() == 0:
            context.close()
            raise RuntimeError(f"کانال «{channel_id}» در نتایج جستجو پیدا نشد")

        # ۵. اگه دکمه‌ی «عضویت» هست کلیکش کن؛ اگه نیست یعنی از قبل عضو بودیم
        join_button = result.locator('button[aria-label="عضویت"]')

        if join_button.count() > 0:
            join_button.click()
            page.wait_for_timeout(2000)

        context.close()
        return True