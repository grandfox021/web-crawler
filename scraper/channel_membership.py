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
        page.wait_for_load_state("networkidle")

        try:
            # ۱. کلیک روی آیکون جستجو
            # نکته: خود svg زیر یک لایه ریپل/inkeffect (div.ZGzps0) قرار داره که
            # همیشه روی آیکون overlay می‌شه و باعث Timeout روی actionability check
            # عادی پلی‌رایت میشه؛ force=True این چک رو دور می‌زنه.
            page.locator('[aria-label="Search-icon"]').click(force=True)

            # ۲. صبر برای باز شدن باکس سرچ (به‌جای timeout ثابت)
            search_input = page.locator('input[type="search"]')
            search_input.wait_for(state="visible")

            # ۳. کلیک روی تب «کانال»
            page.locator("#channel").click(force=True)

            # ۴. تایپ آیدی کانال در سرچ
            # placeholder واقعی فیلد "جستجوی کانال، گروه و پیام..." هست و صرف‌نظر از
            # تب انتخاب‌شده تغییر نمی‌کنه، پس بهتره روی input[type="search"] تکیه کنیم.
            search_input.fill(channel_id)

            # ۵. صبر برای لود نتایج جستجو
            bale_id = channel_id.lstrip("@")
            result = (
                page.locator("[data-item-index]")
                .filter(has_text=bale_id)
                .first
            )
            result.wait_for(state="visible", timeout=15000)

            # ۶. اگه دکمه‌ی «عضویت» هست کلیکش کن؛ اگه نیست یعنی از قبل عضو بودیم
            join_button = result.locator('button[aria-label="عضویت"]')

            if join_button.count() > 0:
                join_button.click(force=True)
                page.wait_for_timeout(2000)

            return True
        except Exception as exc:
            raise RuntimeError(f"کانال «{channel_id}» در نتایج جستجو پیدا نشد یا خطایی رخ داد: {exc}")
        finally:
            context.close()