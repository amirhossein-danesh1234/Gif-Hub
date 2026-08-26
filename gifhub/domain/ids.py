import secrets
import string

from gifhub.domain.normalization import normalize_persian

ALPHABET = string.digits + string.ascii_lowercase


def base36_token(length: int = 3) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def readable_slug(value: str, *, fallback: str = "gif", max_words: int = 2) -> str:
    normalized = normalize_persian(value).lower()
    words: list[str] = []
    for token in normalized.replace("_", " ").split():
        cleaned = "".join(char for char in token if char.isalnum())
        if cleaned:
            words.append(cleaned)
        if len(words) >= max_words:
            break
    return "-".join(words) or fallback


def candidate_gif_id(title: str, tag_ids: tuple[str, ...], *, token: str | None = None) -> str:
    base = readable_slug(title, fallback=tag_ids[0] if tag_ids else "gif")
    suffix = token or base36_token()
    return f"{base}-{suffix}"
