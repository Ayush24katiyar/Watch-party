"""Permission matrix unit tests (architecture section 9, 18.1)."""

import pytest

from watch_party.domain.permissions import can, can_assign, can_remove, can_transfer
from watch_party.domain.roles import Role

# (role, action, expected) - transcribes the section 9 table.
MATRIX = [
    (Role.HOST, "play", True),
    (Role.HOST, "pause", True),
    (Role.HOST, "seek", True),
    (Role.HOST, "change_video", True),
    (Role.HOST, "resolve_request", True),
    (Role.HOST, "assign_role", True),
    (Role.HOST, "remove_participant", True),
    (Role.HOST, "transfer_host", True),
    (Role.HOST, "lock_room", True),
    (Role.HOST, "request_action", False),
    (Role.HOST, "chat", True),
    (Role.HOST, "reaction", True),
    (Role.MODERATOR, "play", True),
    (Role.MODERATOR, "pause", True),
    (Role.MODERATOR, "seek", True),
    (Role.MODERATOR, "change_video", True),
    (Role.MODERATOR, "resolve_request", True),
    (Role.MODERATOR, "assign_role", False),
    (Role.MODERATOR, "remove_participant", False),
    (Role.MODERATOR, "transfer_host", False),
    (Role.MODERATOR, "lock_room", False),
    (Role.MODERATOR, "request_action", False),
    (Role.MODERATOR, "chat", True),
    (Role.MODERATOR, "reaction", True),
    (Role.PARTICIPANT, "play", False),
    (Role.PARTICIPANT, "pause", False),
    (Role.PARTICIPANT, "seek", False),
    (Role.PARTICIPANT, "change_video", False),
    (Role.PARTICIPANT, "resolve_request", False),
    (Role.PARTICIPANT, "assign_role", False),
    (Role.PARTICIPANT, "remove_participant", False),
    (Role.PARTICIPANT, "transfer_host", False),
    (Role.PARTICIPANT, "lock_room", False),
    (Role.PARTICIPANT, "request_action", True),
    (Role.PARTICIPANT, "chat", True),
    (Role.PARTICIPANT, "reaction", True),
]


@pytest.mark.parametrize(("role", "action", "expected"), MATRIX)
def test_matrix(role, action, expected) -> None:
    assert can(role, action) is expected


def test_unknown_action_is_denied() -> None:
    assert can(Role.HOST, "launch_missiles") is False


def test_assign_role_rules() -> None:
    # Only the Host assigns; never to `host`; a Host target blocks self-assignment.
    assert can_assign(Role.HOST, Role.PARTICIPANT, Role.MODERATOR) is True
    assert can_assign(Role.HOST, Role.MODERATOR, Role.PARTICIPANT) is True
    assert can_assign(Role.HOST, Role.PARTICIPANT, Role.HOST) is False
    assert can_assign(Role.HOST, Role.HOST, Role.MODERATOR) is False  # host on self
    assert can_assign(Role.MODERATOR, Role.PARTICIPANT, Role.MODERATOR) is False


def test_remove_rules() -> None:
    assert can_remove(Role.HOST, Role.PARTICIPANT) is True
    assert can_remove(Role.HOST, Role.MODERATOR) is True
    assert can_remove(Role.HOST, Role.HOST) is False  # host on self
    assert can_remove(Role.MODERATOR, Role.HOST) is False  # moderator on host
    assert can_remove(Role.PARTICIPANT, Role.PARTICIPANT) is False


def test_transfer_rules() -> None:
    assert can_transfer(Role.HOST, Role.PARTICIPANT) is True
    assert can_transfer(Role.HOST, Role.MODERATOR) is True
    assert can_transfer(Role.HOST, Role.HOST) is False
    assert can_transfer(Role.MODERATOR, Role.PARTICIPANT) is False
