"""
One-off script to seed the "Cyber Cafe" group (گروه کافه سایبری).

The bot is already a member of this group (it's not joined through the
API's join flow like a channel), so this inserts it directly and marks
its membership as already "joined".

Run once, e.g.:
    python -m db.seed_default_group

After seeding, it behaves exactly like any other entry: it can be toggled
active/inactive via PATCH /channels/{channel_id}, and go-scrap will pick
it up as long as is_active=True.
"""

from db.mongodb import crud_channels
from db.mongodb.channel import MembershipStatus


# TODO: set this to the group's actual Bale id.
# Groups may not have an @handle the way channels do - if that's the case,
# check what Bale exposes for it (invite link id, internal group id, etc.)
# and put that here. This must be unique across the channels collection.
DEFAULT_GROUP = {
    "title": "گروه کافه سایبری",
    "description": "Group the bot is already a member of - scraped like a channel, no join needed.",
    "channel_id": "cyber_cafe_group",  # TODO: replace with the real Bale group id
    "type": "group",
    "is_active": True,
    "importance": 3,
    "orientation": None,
    "activity_field": None,
    "owner": None,
    "execution_interval": "15m",
}


def run() -> dict:
    existing = crud_channels.get_channel_by_channel_id(
        DEFAULT_GROUP["channel_id"]
    )

    if existing:
        print(f"Group already exists: {existing['_id']}")
        return existing

    doc = crud_channels.create_channel(DEFAULT_GROUP)

    # Already a member - mark it joined directly instead of going
    # through the Playwright join flow.
    crud_channels.update_membership_status(
        doc["_id"],
        MembershipStatus.JOINED.value,
    )

    seeded = crud_channels.get_channel(doc["_id"])
    print(f"Seeded group: {seeded['_id']}")
    return seeded


if __name__ == "__main__":
    run()