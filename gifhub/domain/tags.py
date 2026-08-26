from gifhub.domain.models import Tag
from gifhub.domain.normalization import normalize_persian, slugify_persian

TAG_DEFINITIONS: tuple[tuple[str, str, str], ...] = (
    ("laugh", "خنده", "😂"),
    ("happy", "شادی", "😄"),
    ("excited", "ذوق", "🤩"),
    ("hype", "هیجان", "🔥"),
    ("surprised", "تعجب", "😮"),
    ("love", "عشق", "❤️"),
    ("applause", "تشویق", "👏"),
    ("congrats", "تبریک", "🎉"),
    ("sad", "ناراحتی", "😔"),
    ("cry", "گریه", "😭"),
    ("angry", "عصبانیت", "😡"),
    ("confused", "کلافگی", "😵"),
    ("fear", "ترس", "😨"),
    ("shy", "خجالت", "😊"),
    ("ashamed", "شرمندگی", "😬"),
    ("doubt", "تردید", "🤔"),
    ("neutral", "بی‌تفاوتی", "😐"),
    ("silly", "مسخره‌بازی", "🤪"),
    ("sarcasm", "طعنه", "😏"),
    ("interesting", "جالب", "👀"),
    ("yes", "تأیید", "✅"),
    ("no", "مخالفت", "❌"),
    ("thinking", "فکرکردن", "🧠"),
    ("hello", "سلام", "👋"),
    ("goodbye", "خداحافظی", "🙋"),
)


def seed_tags() -> tuple[Tag, ...]:
    return tuple(
        Tag(
            id=tag_id,
            name=name,
            emoji=emoji,
            slug=slugify_persian(name),
            normalized_name=normalize_persian(name),
            sort_order=index,
            is_active=True,
        )
        for index, (tag_id, name, emoji) in enumerate(TAG_DEFINITIONS, start=1)
    )


def active_tag_map(tags: tuple[Tag, ...] | None = None) -> dict[str, Tag]:
    source = tags or seed_tags()
    mapping: dict[str, Tag] = {}
    for tag in source:
        if not tag.is_active:
            continue
        mapping[tag.id] = tag
        mapping[tag.slug] = tag
        mapping[tag.normalized_name] = tag
    return mapping
