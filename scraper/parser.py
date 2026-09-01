import re
from datetime import datetime, timedelta, timezone


IRAN_TZ = timezone(
    timedelta(hours=3, minutes=30)
)


PERSIAN_DIGITS = (
    "۰۱۲۳۴۵۶۷۸۹"
    "٠١٢٣٤٥٦٧٨٩"
)

ENGLISH_DIGITS = (
    "0123456789"
    "0123456789"
)

DIGIT_TRANSLATION_TABLE = str.maketrans(
    PERSIAN_DIGITS,
    ENGLISH_DIGITS,
)


async def clean_body(
    message,
    channel_title=None,
    channel_type=None,
):
    """
    Extract the data of a single Bale message.

    Returns a dict with:

        title
        body
        link
        category
        source_type
        published_at

    plus two technical fields:

        msg_date
        msg_sid
    """

    # ==================================================
    # Message identifiers
    # ==================================================

    msg_sid = await message.get_attribute(
        "data-sid"
    )

    msg_date_raw = await message.get_attribute(
        "data-date"
    )

    msg_date = (
        int(msg_date_raw)
        if msg_date_raw and msg_date_raw.isdigit()
        else None
    )

    # ==================================================
    # Title
    # ==================================================

    strongs = message.locator("strong")

    if await strongs.count() > 0:

        title = (
            await strongs.first.inner_text()
        ).strip()

    else:
        title = None

    # ==================================================
    # Body
    # ==================================================

    spans = message.locator("span.p")

    spans_count = await spans.count()

    body_parts = []

    for j in range(spans_count):

        span = spans.nth(j)

        text = await span.evaluate(
            """
            (el) => {

                const clone =
                    el.cloneNode(true);

                clone.querySelectorAll(
                    'a, .link, .mention, .hashtag'
                ).forEach(
                    element => element.remove()
                );

                return clone.innerText;
            }
            """
        )

        text = text.strip()

        if text:
            body_parts.append(text)

    # ==================================================
    # Drop a title that's duplicated in the body
    # ==================================================

    if title and body_parts:

        if (
            body_parts[0].strip()
            == title.strip()
        ):
            body_parts = body_parts[1:]

    body = " ".join(
        body_parts
    ).strip()

    # ==================================================
    # Drop unwanted lines
    # ==================================================

    lines = []

    for line in body.split("\n"):

        line = line.strip()

        if not line:
            continue

        if "mehrnews.com" in line:
            continue

        lines.append(line)

    body = " ".join(lines).strip()

    # ==================================================
    # Fallback
    # ==================================================

    if not title and body:
        title = body

    if not body and title:
        body = title

    # ==================================================
    # News link
    # ==================================================

    post_url = None

    link = message.locator(
        "span.link"
    ).first

    if await link.count() > 0:

        post_url = (
            await link.inner_text()
        ).strip()

    # ==================================================
    # Published date
    # ==================================================

    published_at = None

    # data-date is the best source.
    if msg_date is not None:

        published_at = datetime.fromtimestamp(
            msg_date / 1000,
            tz=IRAN_TZ,
        )

    else:

        # ----------------------------------------------
        # fall back to the displayed time
        # ----------------------------------------------

        time_element = message.locator(
            "p.x3ai0M"
        ).first

        if await time_element.count() > 0:

            time_text = (
                await time_element.inner_text()
            ).strip()

            time_text = time_text.translate(
                DIGIT_TRANSLATION_TABLE
            )

            match = re.search(
                r"(\d{1,2})\s*:\s*(\d{2})",
                time_text,
            )

            if match:

                hour = int(
                    match.group(1)
                )

                minute = int(
                    match.group(2)
                )

                if (
                    0 <= hour <= 23
                    and 0 <= minute <= 59
                ):

                    now_iran = datetime.now(
                        IRAN_TZ
                    )

                    published_at = (
                        now_iran.replace(
                            hour=hour,
                            minute=minute,
                            second=0,
                            microsecond=0,
                        )
                    )

    # ==================================================
    # Category (previously "source")
    #
    # Taken from the @mention inside the message when
    # present, otherwise falls back to the channel title.
    # ==================================================

    mention = message.locator(
        "span.mention"
    ).first

    mention_category = None

    if await mention.count() > 0:

        mention_category = (
            await mention.get_attribute(
                "data-mention"
            )
        )

        if not mention_category:

            mention_category = (
                await mention.inner_text()
            )

        if mention_category:

            mention_category = (
                mention_category
                .strip()
                .lstrip("@")
            )

    category = (
        mention_category
        or channel_title
        or "unknown"
    )

    source_type = (
        channel_type
        or "bale_channel"
    )

    # ==================================================
    # Output
    # ==================================================

    return {
        "title": title,
        "body": body,
        "link": post_url,
        "category": category,
        "source_type": source_type,
        "published_at": published_at,

        # technical fields
        "msg_date": msg_date,
        "msg_sid": msg_sid,
    }