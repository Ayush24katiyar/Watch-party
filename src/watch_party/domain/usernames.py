"""Username uniqueness (R-3): per room, case-insensitive, "Akshay" -> "Akshay#2"."""

import re
from typing import Iterable

# Strip control characters (S-10); React escaping handles XSS on the client.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def sanitize_username(raw: str) -> str:
    cleaned = _CONTROL_CHARS.sub("", raw).strip()
    return cleaned[:24] or "user"


def unique_username(desired: str, taken: Iterable[str]) -> str:
    """Return `desired`, or `desired#2`, `#3`, ... until the name is free."""
    base = sanitize_username(desired)
    lowered_taken = {name.casefold() for name in taken}
    candidate = base
    suffix = 2
    while candidate.casefold() in lowered_taken:
        candidate = f"{base}#{suffix}"
        suffix += 1
    return candidate
