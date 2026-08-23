import os
from typing import Optional

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
)

from db.mongodb import crud_channels
from db.mongodb.channel import (
    ChannelCreate,
    ChannelStatusUpdate,
    MembershipStatus,
)
from db.mongodb.seed_default_group import DEFAULT_GROUP
from scraper.channel_membership import (
    join_channel_in_bale,
)
from scraper.locks import (
    acquire_lock,
    release_lock,
)


router = APIRouter(
    prefix="/channels",
    tags=["channels"],
)


# Join and the scraper both use the same shared Playwright profile,
# so they need to coordinate through the same lock.
JOIN_LOCK_TIMEOUT = int(
    os.getenv(
        "JOIN_LOCK_TIMEOUT",
        "120",
    )
)


def _try_join(
    channel_id: str,
) -> bool:
    """
    Attempt to join the Bale channel.

    If the lock can't be acquired, a scrape run or another join
    operation is already in progress.
    """

    if not acquire_lock(
        JOIN_LOCK_TIMEOUT
    ):

        raise HTTPException(
            status_code=409,
            detail=(
                "Another scrape run or join operation "
                "is already in progress."
            ),
        )

    try:

        result = join_channel_in_bale(
            channel_id
        )

        if not result:

            raise HTTPException(
                status_code=502,
                detail=(
                    "Failed to join the Bale channel."
                ),
            )

        return True

    except HTTPException:
        raise

    except Exception as e:

        raise HTTPException(
            status_code=502,
            detail=(
                f"Error joining Bale channel: {str(e)}"
            ),
        )

    finally:

        release_lock()


@router.post(
    "",
    status_code=201,
)
def create_channel(
    payload: ChannelCreate,
):
    """
    Create a channel:

        1. join
        2. if join succeeded -> save to Mongo
    """

    data = payload.dict()

    existing_channel = crud_channels.get_channel_by_channel_id(
        data.get("channel_id")
    )
    if existing_channel:
        raise HTTPException(
            status_code=400,
            detail="This channel already exists in the database.",
        )

    is_group = data.get("type") == "group"

    # ----------------------------------------------
    # join first (groups are already a member - skip)
    # ----------------------------------------------

    if not is_group:

        _try_join(
            data["channel_id"]
        )

    # ----------------------------------------------
    # then save to Mongo
    # ----------------------------------------------

    try:

        doc = crud_channels.create_channel(
            data
        )

    except ValueError as e:

        raise HTTPException(
            status_code=409,
            detail=str(e),
        )

    # ----------------------------------------------
    # membership status
    #
    # for a group, we're already a member - mark it joined
    # directly instead of going through the join flow.
    # ----------------------------------------------

    crud_channels.update_membership_status(
        doc["_id"],
        MembershipStatus.JOINED.value,
    )

    return crud_channels.get_channel(
        doc["_id"]
    )


@router.post(
    "/default-group",
    status_code=201,
)
def create_default_group():
    """
    Adds the pre-configured "Cyber Cafe" group (گروه کافه سایبری).

    The bot is already a member of this group, so this skips the join
    flow entirely and marks membership as joined directly - unlike
    POST /channels, which requires an actual join for type="channel".

    Idempotent: calling this again after the group already exists just
    returns the existing document instead of erroring.
    """

    existing = crud_channels.get_channel_by_channel_id(
        DEFAULT_GROUP["channel_id"]
    )

    if existing:
        return existing

    doc = crud_channels.create_channel(
        DEFAULT_GROUP
    )

    crud_channels.update_membership_status(
        doc["_id"],
        MembershipStatus.JOINED.value,
    )

    return crud_channels.get_channel(
        doc["_id"]
    )


@router.get("")
def list_channels(
    is_active: Optional[bool] = Query(
        default=None,
        description="Filter by active status",
    ),
    q: Optional[str] = Query(
        default=None,
        description="Search by title or description",
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
):
    """
    List channels (paginated, optionally filtered by status and/or searched by q).
    """

    return crud_channels.list_channels(
        is_active=is_active,
        q=q,
        page_number=page_number,
        page_size=page_size,
    )


@router.get(
    "/{channel_id}"
)
def get_channel(
    channel_id: str,
):
    """
    Get a channel by its internal Mongo ID.
    """

    doc = crud_channels.get_channel(
        channel_id
    )

    if not doc:

        raise HTTPException(
            status_code=404,
            detail="Channel not found.",
        )

    return doc


@router.get(
    "/by-channel-id/{bale_channel_id}"
)
def get_channel_by_channel_id(
    bale_channel_id: str,
):
    """
    Get a channel by its Bale channel_id.
    """

    doc = (
        crud_channels
        .get_channel_by_channel_id(
            bale_channel_id
        )
    )

    if not doc:

        raise HTTPException(
            status_code=404,
            detail="Channel not found.",
        )

    return doc


@router.patch(
    "/{channel_id}"
)
def update_channel_status(
    channel_id: str,
    payload: ChannelStatusUpdate,
):
    """
    Toggle a channel/group's active status. This is the only thing
    PATCH does - for a full update, use PUT instead.
    """

    doc = crud_channels.update_channel(
        channel_id,
        {"is_active": payload.is_active},
    )

    if not doc:

        raise HTTPException(
            status_code=404,
            detail="Channel not found.",
        )

    return doc


@router.put(
    "/{channel_id}"
)
def replace_channel(
    channel_id: str,
    payload: ChannelCreate,
):
    """
    Full update: every field in the request body replaces the stored value.

    If the Bale channel_id changes on a channel-type entry, it's joined
    again under the new id (groups skip this - membership already exists).
    """

    existing = crud_channels.get_channel(
        channel_id
    )

    if not existing:

        raise HTTPException(
            status_code=404,
            detail="Channel not found.",
        )

    data = payload.dict()

    channel_id_changed = (
        data["channel_id"]
        != existing["channel_id"]
    )

    try:

        doc = crud_channels.replace_channel(
            channel_id,
            data,
        )

    except ValueError as e:

        raise HTTPException(
            status_code=409,
            detail=str(e),
        )

    # ----------------------------------------------
    # Bale channel_id changed on a channel (not a group)
    # ----------------------------------------------

    if (
        channel_id_changed
        and data.get("type") != "group"
    ):

        _try_join(
            data["channel_id"]
        )

        doc = crud_channels.get_channel(
            channel_id
        )

    return doc


# @router.post(
#     "/{channel_id}/rejoin"
# )
# def rejoin_channel(
#     channel_id: str,
# ):
#     """
#     Manually re-join the channel.
#     """

#     doc = crud_channels.get_channel(
#         channel_id
#     )

#     if not doc:

#         raise HTTPException(
#             status_code=404,
#             detail="Channel not found.",
#         )

#     if not acquire_lock(
#         JOIN_LOCK_TIMEOUT
#     ):

#         raise HTTPException(
#             status_code=409,
#             detail=(
#                 "Another scrape run or join operation "
#                 "is already in progress."
#             ),
#         )

#     try:

#         result = join_channel_in_bale(
#             doc["channel_id"]
#         )

#         if not result:

#             raise RuntimeError(
#                 "Failed to join the Bale channel."
#             )

#         crud_channels.update_membership_status(
#             channel_id,
#             MembershipStatus.JOINED.value,
#         )

#     except Exception as e:

#         crud_channels.update_membership_status(
#             channel_id,
#             MembershipStatus.FAILED.value,
#             error=str(e),
#         )

#         raise HTTPException(
#             status_code=502,
#             detail=str(e),
#         )

#     finally:

#         release_lock()

#     return crud_channels.get_channel(
#         channel_id
#     )


@router.delete(
    "/{channel_id}",
    status_code=204,
)
def delete_channel(
    channel_id: str,
):
    """
    Delete a channel.
    """

    ok = crud_channels.delete_channel(
        channel_id
    )

    if not ok:

        raise HTTPException(
            status_code=404,
            detail="Channel not found.",
        )