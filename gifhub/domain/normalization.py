import re
import unicodedata

ZERO_WIDTH_CHARS = ("\u200c", "\u200d", "\u200e", "\u200f", "\ufeff")
PERSIAN_TRANSLATION = str.maketrans(
    {
        "ي": "ی",
        "ى": "ی",
        "ك": "ک",
        "ة": "ه",
        "ۀ": "ه",
        "ؤ": "و",
        "إ": "ا",
        "أ": "ا",
        "ٱ": "ا",
    }
)
DIACRITIC_RE = re.compile(r"[\u064b-\u065f\u0670]")
WHITESPACE_RE = re.compile(r"\s+")


def normalize_persian(value: str) -> str:
    text = unicodedata.normalize("NFKC", value)
    text = text.translate(PERSIAN_TRANSLATION)
    text = DIACRITIC_RE.sub("", text)
    for char in ZERO_WIDTH_CHARS:
        text = text.replace(char, " ")
    text = text.replace("-", " ")
    text = WHITESPACE_RE.sub(" ", text)
    return text.strip().casefold()


def slugify_persian(value: str) -> str:
    normalized = normalize_persian(value)
    return normalized.replace(" ", "-")
