from gifhub.domain.models import GifStatus

ALLOWED_TRANSITIONS: dict[GifStatus, set[GifStatus]] = {
    GifStatus.DRAFT: {GifStatus.PENDING, GifStatus.REJECTED},
    GifStatus.PENDING: {GifStatus.APPROVED, GifStatus.REJECTED},
    GifStatus.APPROVED: set(),
    GifStatus.REJECTED: set(),
}


def can_transition(current: GifStatus, target: GifStatus) -> bool:
    return target in ALLOWED_TRANSITIONS[current]


def ensure_transition(current: GifStatus, target: GifStatus) -> None:
    if not can_transition(current, target):
        raise ValueError(f"Invalid GIF transition: {current} -> {target}")


def can_moderate(is_admin: bool, status: GifStatus) -> bool:
    return is_admin and status == GifStatus.PENDING
