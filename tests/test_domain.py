from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from gifhub.domain.hash import sha256_file
from gifhub.domain.ids import candidate_gif_id, readable_slug
from gifhub.domain.models import GifStatus, SearchableGif
from gifhub.domain.normalization import normalize_persian
from gifhub.domain.parser import parse_manual_tags
from gifhub.domain.search import rank_gifs, score_gif
from gifhub.domain.state import can_moderate, can_transition, ensure_transition


def test_persian_normalization_handles_arabic_letters_and_half_space() -> None:
    assert normalize_persian("مسخره‌ بازی") == normalize_persian("مسخره بازی")
    assert normalize_persian("كلافگي") == normalize_persian("کلافگی")


def test_manual_tag_parser_validates_whitelist_duplicates_and_max_three() -> None:
    parsed = parse_manual_tags("<خنده> <جالب> <خنده> <باحال>")
    assert [tag.id for tag in parsed.valid] == ["laugh", "interesting"]
    assert [tag.id for tag in parsed.duplicates_removed] == ["laugh"]
    assert parsed.invalid == ("باحال",)

    too_many = parse_manual_tags("laugh happy excited hype")
    assert [tag.id for tag in too_many.valid] == ["laugh", "happy", "excited"]
    assert too_many.invalid == ("حداکثر 3 تگ مجاز است",)


@pytest.mark.parametrize("value", ["<مسخره بازی>", "<مسخره‌بازی>", "silly"])
def test_manual_tag_parser_normalizes_spacing_variants(value: str) -> None:
    parsed = parse_manual_tags(value)
    assert parsed.valid[0].id == "silly"
    assert parsed.invalid == ()


def test_human_readable_id_candidate_is_short_and_non_numeric() -> None:
    assert readable_slug("Laugh Cat") == "laugh-cat"
    assert candidate_gif_id("Laugh Cat", ("laugh",), token="83k") == "laugh-cat-83k"


def test_sha256_file(tmp_path: Path) -> None:
    path = tmp_path / "sample.txt"
    path.write_text("gifhub", encoding="utf-8")
    assert sha256_file(path) == "5c819d23e73b729e99796af3a7e2ba3103540f7a477b6fc6b5db134cf0a5af34"


def test_state_machine_and_permission_checks() -> None:
    assert can_transition(GifStatus.DRAFT, GifStatus.PENDING)
    assert not can_transition(GifStatus.DRAFT, GifStatus.APPROVED)
    ensure_transition(GifStatus.PENDING, GifStatus.APPROVED)
    assert can_moderate(True, GifStatus.PENDING)
    assert not can_moderate(False, GifStatus.PENDING)


def test_search_ranking_uses_tag_title_usage_and_age_penalty() -> None:
    now = datetime.now(tz=UTC)
    fresh_popular = SearchableGif(
        id="laugh-cat-83k",
        title="Laugh cat",
        tag_names=("خنده", "جالب"),
        tag_ids=("laugh", "interesting"),
        approved_at=now - timedelta(days=1),
        usage_count=10,
    )
    old = SearchableGif(
        id="laugh-dog-k2p",
        title="Laugh dog",
        tag_names=("خنده",),
        tag_ids=("laugh",),
        approved_at=now - timedelta(days=100),
        usage_count=1,
    )
    assert score_gif(fresh_popular, query="cat", query_tag_ids=("laugh",), now=now) > score_gif(
        old,
        query="cat",
        query_tag_ids=("laugh",),
        now=now,
    )
    assert [
        item.id for item in rank_gifs((old, fresh_popular), query="laugh", query_tag_ids=("laugh",))
    ] == ["laugh-cat-83k", "laugh-dog-k2p"]
