from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class MembershipStatus(str, Enum):
    QUEUED = "queued"
    JOINED = "joined"
    FAILED = "failed"


class ExecutionInterval(str, Enum):
    FIVE_MIN = "5m"
    FIFTEEN_MIN = "15m"
    THIRTY_MIN = "30m"
    ONE_HOUR = "1h"
    THREE_HOURS = "3h"
    SIX_HOURS = "6h"
    TWELVE_HOURS = "12h"
    TWENTY_FOUR_HOURS = "24h"


class ChannelBase(BaseModel):
    title: str = Field(..., min_length=1)
    description: Optional[str] = None
    # Channel id on Bale - e.g. "@iribnews" - used for both membership and search
    channel_id: str
    # True = active, False = inactive. Real boolean, not a string.
    is_active: bool = True
    # 1 (lowest) to 5 (highest)
    importance: int = Field(3, ge=1, le=5)
    orientation: Optional[str] = None
    activity_field: Optional[str] = None
    owner: Optional[str] = None
    execution_interval: Optional[ExecutionInterval] = None

    model_config = {"populate_by_name": True}


class ChannelCreate(ChannelBase):
    """Request body for creating a new channel."""

    pass


class ChannelUpdate(BaseModel):
    """All fields optional; only what's sent gets updated (PATCH)."""

    title: Optional[str] = None
    description: Optional[str] = None
    channel_id: Optional[str] = None
    is_active: Optional[bool] = None
    importance: Optional[int] = Field(None, ge=1, le=5)
    orientation: Optional[str] = None
    activity_field: Optional[str] = None
    owner: Optional[str] = None
    execution_interval: Optional[ExecutionInterval] = None

    model_config = {"populate_by_name": True}


class ChannelOut(ChannelBase):
    id: str = Field(..., alias="_id")
    membership_status: Optional[MembershipStatus] = None
    membership_error: Optional[str] = None

    model_config = {"populate_by_name": True}