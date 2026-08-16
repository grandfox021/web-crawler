from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ChannelStatus(str, Enum):
    ACTIVE = "فعال"
    INACTIVE = "غیرفعال"


class ImportanceLevel(str, Enum):
    VERY_LOW = "خیلی کم"
    LOW = "کم"
    MEDIUM = "متوسط"
    HIGH = "زیاد"
    VERY_HIGH = "خیلی زیاد"


class MembershipStatus(str, Enum):
    QUEUED = "در صف عضویت"
    JOINED = "عضو شد"
    FAILED = "خطا در عضویت"


class ExecutionInterval(str, Enum):
    FIVE_MIN = "5 دقیقه"
    FIFTEEN_MIN = "15 دقیقه"
    THIRTY_MIN = "30 دقیقه"
    ONE_HOUR = "1 ساعت"
    THREE_HOURS = "3 ساعت"
    SIX_HOURS = "6 ساعت"
    TWELVE_HOURS = "12 ساعت"
    TWENTY_FOUR_HOURS = "1 روز"


class ChannelBase(BaseModel):
    title: str = Field(..., alias="عنوان کانال", min_length=1)
    description: Optional[str] = Field(None, alias="توضیحات")
    # آیدی کانال در بله - مثلا "@iribnews" - همینه که برای عضویت و سرچ استفاده می‌شه
    channel_id: str = Field(..., alias="آیدی کانال")
    status: ChannelStatus = Field(ChannelStatus.ACTIVE, alias="وضعیت")
    language: Optional[str] = Field(None, alias="زبان")
    importance: ImportanceLevel = Field(ImportanceLevel.MEDIUM, alias="سطح اهمیت")
    founded_year: Optional[int] = Field(None, alias="سال تاسیس")
    orientation: Optional[str] = Field(None, alias="جهت گیری")
    activity_field: Optional[str] = Field(None, alias="زمینه فعالیت")
    owner: Optional[str] = Field(None, alias="مالک کانال")
    execution_interval: Optional[ExecutionInterval] = Field(
        None, alias="زمان اجرا"
    )

    model_config = {"populate_by_name": True}


class ChannelCreate(ChannelBase):
    """بدنه‌ی درخواست ساخت کانال جدید."""

    pass


class ChannelUpdate(BaseModel):
    """همه‌ی فیلدها اختیاری‌اند؛ فقط چیزی که ارسال بشه آپدیت می‌شود (PATCH)."""

    title: Optional[str] = Field(None, alias="عنوان کانال")
    description: Optional[str] = Field(None, alias="توضیحات")
    channel_id: Optional[str] = Field(None, alias="آیدی کانال")
    status: Optional[ChannelStatus] = Field(None, alias="وضعیت")
    language: Optional[str] = Field(None, alias="زبان")
    importance: Optional[ImportanceLevel] = Field(None, alias="سطح اهمیت")
    founded_year: Optional[int] = Field(None, alias="سال تاسیس")
    orientation: Optional[str] = Field(None, alias="جهت گیری")
    activity_field: Optional[str] = Field(None, alias="زمینه فعالیت")
    owner: Optional[str] = Field(None, alias="مالک کانال")
    execution_interval: Optional[ExecutionInterval] = Field(
        None, alias="زمان اجرا"
    )

    model_config = {"populate_by_name": True}


class ChannelOut(ChannelBase):
    id: str = Field(..., alias="_id")
    membership_status: Optional[MembershipStatus] = Field(None, alias="وضعیت عضویت")
    membership_error: Optional[str] = Field(None, alias="خطای عضویت")

    model_config = {"populate_by_name": True}