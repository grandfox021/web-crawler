import os
from datetime import datetime

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
)

from scraper.bale_scraper import scrape_all_channels
from scraper.locks import acquire_lock, release_lock
from scraper.parser import IRAN_TZ
from db.mongodb.crud import get_news_from_db


router = APIRouter(
    tags=["scrap"],
)


# If a run takes longer than this (e.g. it crashed and never released
# the lock), the lock is released automatically so the next run can
# pick it up.
LOCK_TIMEOUT = int(
    os.getenv(
        "SCRAPE_LOCK_TIMEOUT",
        "600",
    )
)  # 10 minutes


def _parse_date(
    value: str,
    param_name: str,
) -> datetime:
    """
    Parses an ISO-8601 date/datetime string.

    Examples:
        2026-08-20
        2026-08-20T10:00:00

    If no timezone is given, assumes Iran time,
    since published_at is stored using Iran timezone.
    """

    try:

        parsed = datetime.fromisoformat(
            value
        )

    except ValueError:

        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid {param_name}: expected ISO-8601 format, "
                f"e.g. '2026-08-20' or "
                f"'2026-08-20T10:00:00'."
            ),
        )

    if parsed.tzinfo is None:

        parsed = parsed.replace(
            tzinfo=IRAN_TZ
        )

    return parsed


@router.post(
    "/scrape-channels"
)
async def go_scrap():
    """
    Called by Airflow.

    Waits for scraping of all active channels to finish
    and returns a summary of the result.

    Note:
        Since this is a long-running operation
        (Playwright + several channels), the HTTP operator
        timeout in Airflow and any reverse proxy in front
        of this service need to be configured accordingly.
    """

    if not acquire_lock(
        LOCK_TIMEOUT
    ):

        raise HTTPException(
            status_code=409,
            detail=(
                "Another scrape run is already in progress."
            ),
        )

    try:

        summary = await scrape_all_channels()

    finally:

        release_lock()

    return {
        "channels_succeeded": len(
            summary["success"]
        ),
        "channels_failed": len(
            summary["failed"]
        ),
        "details": summary,
    }


@router.get(
    "/get-news"
)
def get_news(
    q: str | None = Query(
        default=None,
        description="Search by title or body",
    ),
    page_number: int = Query(
        default=1,
        ge=1,
        description="1-based page index",
    ),
    page_size: int = Query(
        default=10,
        ge=1,
        le=100,
        description="Items per page",
    ),
    start_date: str | None = Query(
        default=None,
        description=(
            "Filter news published from this date. "
            "ISO-8601 format."
        ),
    ),
    end_date: str | None = Query(
        default=None,
        description=(
            "Filter news published until this date. "
            "ISO-8601 format."
        ),
    ),
):

    parsed_start = (
        _parse_date(
            start_date,
            "start_date",
        )
        if start_date
        else None
    )

    parsed_end = (
        _parse_date(
            end_date,
            "end_date",
        )
        if end_date
        else None
    )

    return get_news_from_db(
        q=q,
        page_number=page_number,
        page_size=page_size,
        start_date=parsed_start,
        end_date=parsed_end,
    )