"""Room-code generation (architecture section 8.1).

6 characters from a 31-char alphabet without visually ambiguous symbols
(no 0/O/1/I/L): about 887M combinations, case-insensitive on lookup.
"""

import secrets

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 6


def generate_room_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def normalize_code(code: str) -> str:
    """Codes are case-insensitive on input (8.1)."""
    return code.strip().upper()
