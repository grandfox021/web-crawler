from playwright.sync_api import sync_playwright
from fastapi import FastAPI
import uvicorn
import time

app = FastAPI()

mydb = []

def clean_body(page, message):
    strongs = message.locator("strong")
    title = strongs.first.inner_text().strip() if strongs.count() > 0 else None

    spans = message.locator("span.p")
    spans_count = spans.count()

    body_parts = []
    for j in range(spans_count):
        span = spans.nth(j)

        # یک کپی از innerHTML بگیر و لینک‌ها/منشن‌ها رو حذف کن
        html = span.evaluate("""(el) => {
            const clone = el.cloneNode(true);
            clone.querySelectorAll('a, .link, .mention, .hashtag').forEach(e => e.remove());
            return clone.innerText;
        }""")

        text = html.strip()
        if text:
            body_parts.append(text)

    if title and body_parts and body_parts[0].strip() == title.strip():
        body_parts = body_parts[1:]

    body = "\n".join(body_parts).strip()

    # فیلتر خط‌های باقی‌مانده‌ای که فقط دامنه سایت یا خالی هستن
    lines = [ln for ln in body.split("\n") if ln.strip() and "mehrnews.com" not in ln]
    body = "\n".join(lines).strip()

    return title, body

def scrape_news():
    news = []
    with sync_playwright() as p:

        context = p.chromium.launch_persistent_context(
            user_data_dir="./profile",
            headless=False,
        )

        page = context.pages[0] if context.pages else context.new_page()

        page.goto("https://web.bale.ai")

        channel = page.locator('[aria-label="dialog-item"]').filter(
            has_text="خبرگزاری مهر"
        )
        channel.click()

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

        messages = page.locator(".KTwPFW")
        messages_count = messages.count()

        print("Total:", messages_count)

        for i in range(messages_count):
            message = messages.nth(i)
            title, body = clean_body(page, message)

            print(f"\n===== {i} =====")
            print(f"Title: {title}")
            print(f"Body : {body}")

            news.append({
                "index": i,
                "title": title,
                "body": body,
            })
        context.close()
    print(f"\nذخیره شد: {len(news)} پیام")
    return news    
    # print(f"\nذخیره شد: {len(news)} پیام")

    # page.pause()

@app.get("/news")
def get_news():

    news = scrape_news()
    # time.sleep(20)
    return {
        "count": len(news),
        "data": news,
    }

uvicorn.run(app)