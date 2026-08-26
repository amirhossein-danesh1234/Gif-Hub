from datetime import UTC, datetime
from math import log1p

from gifhub.domain.models import SearchableGif
from gifhub.domain.normalization import normalize_persian


def title_match_score(title: str, query: str) -> float:
    normalized_title = normalize_persian(title)
    normalized_query = normalize_persian(query)
    if not normalized_query:
        return 0.0
    if normalized_query in normalized_title:
        return 1.0
    query_tokens = [token for token in normalized_query.split() if token]
    if not query_tokens:
        return 0.0
    matched = sum(1 for token in query_tokens if token in normalized_title)
    return matched / len(query_tokens)


def score_gif(
    gif: SearchableGif,
    *,
    query: str = "",
    query_tag_ids: tuple[str, ...] = (),
    now: datetime | None = None,
) -> float:
    now = now or datetime.now(tz=UTC)
    query_tags = set(query_tag_ids)
    gif_tags = set(gif.tag_ids)
    tag_match = len(query_tags & gif_tags)
    title_match = title_match_score(gif.title, query)
    usage_count_log = log1p(max(gif.usage_count, 0))
    age_days = max((now - gif.approved_at).total_seconds() / 86_400, 0.0)
    age_penalty = age_days / 365

    return (tag_match * 3) + (title_match * 2) + usage_count_log - (age_penalty * 0.5)


def rank_gifs(
    gifs: tuple[SearchableGif, ...],
    *,
    query: str = "",
    query_tag_ids: tuple[str, ...] = (),
) -> tuple[SearchableGif, ...]:
    if not query and not query_tag_ids:
        return tuple(sorted(gifs, key=lambda gif: gif.usage_count, reverse=True))

    ranked: list[tuple[float, SearchableGif]] = []
    for gif in gifs:
        has_tag_match = bool(set(query_tag_ids) & set(gif.tag_ids)) if query_tag_ids else True
        has_title_match = title_match_score(gif.title, query) > 0 if query else True
        if has_tag_match and has_title_match:
            ranked.append((score_gif(gif, query=query, query_tag_ids=query_tag_ids), gif))

    return tuple(gif for _, gif in sorted(ranked, key=lambda item: item[0], reverse=True))


def score_media(
    media: SearchableGif,
    query_tags: tuple[str, ...],
    *,
    now: datetime | None = None,
) -> float:
    return score_gif(media, query_tag_ids=query_tags, now=now)


def rank_media(
    media_items: tuple[SearchableGif, ...],
    query_tags: tuple[str, ...],
) -> tuple[SearchableGif, ...]:
    return rank_gifs(media_items, query_tag_ids=query_tags)
