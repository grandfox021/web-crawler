from datetime import datetime, timedelta, timezone
import re


def clean_body(message, channel_title=None, channel_type=None):

    # ---------------------------
    # عنوان
    # ---------------------------

    strongs = message.locator("strong")

    title = (
        strongs.first.inner_text().strip()
        if strongs.count() > 0
        else None
    )

    # ---------------------------
    # متن
    # ---------------------------

    spans = message.locator("span.p")
    spans_count = spans.count()

    body_parts = []

    for j in range(spans_count):

        span = spans.nth(j)

        html = span.evaluate("""
            (el) => {
                const clone = el.cloneNode(true);

                clone.querySelectorAll(
                    'a, .link, .mention, .hashtag'
                ).forEach(e => e.remove());

                return clone.innerText;
            }
        """)

        text = html.strip()

        if text:
            body_parts.append(text)

    if title and body_parts:
        if body_parts[0].strip() == title.strip():
            body_parts = body_parts[1:]

    body = " ".join(body_parts).strip()

    lines = [
        line
        for line in body.split("\n")
        if line.strip()
        and "mehrnews.com" not in line
    ]

    body = " ".join(lines).strip()

    # ---------------------------
    # fallback
    # ---------------------------

    if not title and body:
        title = body

    if not body and title:
        body = title

    # ---------------------------
    # لینک خبر
    # ---------------------------

    post_url = None

    link = message.locator("span.link").first

    if link.count() > 0:
        post_url = link.inner_text().strip()

    # ---------------------------
    # تاریخ انتشار
    # ---------------------------

    IRAN_TZ = timezone(timedelta(hours=3, minutes=30))

    published_at = None

    time_element = message.locator("p.x3ai0M").first

    if time_element.count() > 0:

        time_text = time_element.inner_text().strip()

        # تبدیل اعداد فارسی و عربی به انگلیسی
        translation_table = str.maketrans(
            "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
            "01234567890123456789"
        )

        time_text = time_text.translate(translation_table)

        match = re.search(
            r"(\d{1,2})\s*:\s*(\d{2})",
            time_text
        )

        if match:

            hour = int(match.group(1))
            minute = int(match.group(2))

            if 0 <= hour <= 23 and 0 <= minute <= 59:

                # تاریخ امروز ایران
                now_iran = datetime.now(IRAN_TZ)

                # تاریخ امروز + ساعت پست
                published_at = now_iran.replace(
                    hour=hour,
                    minute=minute,
                    second=0,
                    microsecond=0
                )

    # ---------------------------
    # منبع - قبلاً هاردکد بود، حالا از خود کانال میاد
    # ---------------------------

    source = channel_title or "نامشخص"
    source_type = channel_type or "کانال بله"

    return {
        "عنوان": title,
        "متن": body,
        "لینک": post_url,
        "منبع": source,
        "نوع منبع": source_type,
        "تاریخ انتشار": published_at,
    }