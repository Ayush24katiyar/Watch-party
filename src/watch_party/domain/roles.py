"""Role enum (architecture section 9)."""

from enum import Enum


class Role(str, Enum):
    HOST = "host"
    MODERATOR = "moderator"
    PARTICIPANT = "participant"
