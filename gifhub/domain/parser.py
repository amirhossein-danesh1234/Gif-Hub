import re
from dataclasses import dataclass

from gifhub.domain.models import Tag
from gifhub.domain.normalization import normalize_persian
from gifhub.domain.tags import active_tag_map, seed_tags

TAG_PATTERN = re.compile(r"<([^<>]+)>")


@dataclass(frozen=True)
class ParsedTags:
    valid: tuple[Tag, ...]
    invalid: tuple[str, ...]
    duplicates_removed: tuple[Tag, ...]

    @property
    def is_valid(self) -> bool:
        return not self.invalid


class TagValidationError(ValueError):
    pass


def parse_manual_tags(
    text: str,
    *,
    tags: tuple[Tag, ...] | None = None,
    min_count: int = 1,
    max_count: int = 3,
) -> ParsedTags:
    whitelist = active_tag_map(tags or seed_tags())
    seen: set[str] = set()
    valid: list[Tag] = []
    duplicate_tags: list[Tag] = []
    invalid: list[str] = []

    raw_values = TAG_PATTERN.findall(text)
    if not raw_values and text.strip():
        raw_values = text.replace(",", " ").split()

    for raw_tag in raw_values:
        value = raw_tag.strip()
        normalized = normalize_persian(value)
        tag = whitelist.get(value) or whitelist.get(value.lower()) or whitelist.get(normalized)
        if tag is None:
            invalid.append(value)
            continue
        if tag.id in seen:
            duplicate_tags.append(tag)
            continue
        seen.add(tag.id)
        valid.append(tag)

    if len(valid) < min_count:
        invalid.append(f"حداقل {min_count} تگ لازم است")
    if len(valid) > max_count:
        invalid.append(f"حداکثر {max_count} تگ مجاز است")

    return ParsedTags(
        valid=tuple(valid[:max_count]),
        invalid=tuple(invalid),
        duplicates_removed=tuple(duplicate_tags),
    )


def format_tag_list(tags: tuple[Tag, ...]) -> str:
    return " ".join(f"{tag.emoji} {tag.name}" for tag in tags)
