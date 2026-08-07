from dataclasses import dataclass


@dataclass(frozen=True)
class AvailabilityChange:
    listing_id: int
    kind: str  # new | reappeared


def changes_for_snapshot(
    previous: dict[int, bool], current: set[int], initialized: bool
) -> list[AvailabilityChange]:
    if not initialized:
        return []
    return [
        AvailabilityChange(listing_id, "reappeared" if listing_id in previous else "new")
        for listing_id in current
        if not previous.get(listing_id, False)
    ]
