from playwright.sync_api import sync_playwright

from .parser import clean_body


def scrape_news():

    news = []

    with sync_playwright() as p:

        context = p.chromium.launch_persistent_context(
            user_data_dir="./profile",
            headless=True,
        )

        page = (
            context.pages[0]
            if context.pages
            else context.new_page()
        )

        page.goto("https://web.bale.ai")

        channel = (
            page
            .locator('[aria-label="dialog-item"]')
            .filter(has_text="خبرگزاری مهر")
        )

        channel.click()

        page.wait_for_timeout(2000)

        stable_count = 0

        while stable_count < 3:

            old_height = page.evaluate(
                "document.body.scrollHeight"
            )

            page.mouse.wheel(0, 5000)

            page.wait_for_timeout(2000)

            new_height = page.evaluate(
                "document.body.scrollHeight"
            )

            if old_height == new_height:
                stable_count += 1
            else:
                stable_count = 0

        messages = page.locator(".message-item")
        messages_count = messages.count()

        print("Total:", messages_count)

        for i in range(messages_count):

            message = messages.nth(i)

            # print("=" * 80)
            # print("MESSAGE:", i)
            # print(message.inner_text())
            # print("STRONG COUNT:", message.locator("strong").count())

            parsed_news = clean_body(message)

            if (
                not parsed_news["عنوان"]
                and not parsed_news["متن"]
            ):
                continue

            news.append(parsed_news)

        context.close()

    return news