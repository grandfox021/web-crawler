def clean_body(message):
    strongs = message.locator("strong")

    title = (
        strongs.first.inner_text().strip()
        if strongs.count() > 0
        else None
    )

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
    # fallback title / body
    # ---------------------------

    if not title and body:
        title = body

    if not body and title:
        body = title

    return {
        "title": title,
        "body": body,
    }