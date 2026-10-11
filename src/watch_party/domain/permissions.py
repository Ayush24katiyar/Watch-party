"""Permission matrix (architecture section 9).

Pure functions used by the MessageRouter BEFORE any handler runs: the backend,
not the UI, decides who may do what. Hard rules (9):

- exactly one Host per room at all times;
- a Moderator can never act on the Host;
- nobody can assign `host` through assign_role (D-17);
- the Host cannot assign a role to, or remove, themselves.
"""

from watch_party.domain.roles import Role

# Section 9 table: action -> allowed roles.
_PERMISSIONS: dict[str, frozenset[Role]] = {
    "play": frozenset({Role.HOST, Role.MODERATOR}),
    "pause": frozenset({Role.HOST, Role.MODERATOR}),
    "seek": frozenset({Role.HOST, Role.MODERATOR}),
    "change_video": frozenset({Role.HOST, Role.MODERATOR}),
    "resolve_request": frozenset({Role.HOST, Role.MODERATOR}),
    "assign_role": frozenset({Role.HOST}),
    "remove_participant": frozenset({Role.HOST}),
    "transfer_host": frozenset({Role.HOST}),
    "lock_room": frozenset({Role.HOST}),
    # request_action is the Participant's path to ask for a change (Phase 6).
    "request_action": frozenset({Role.PARTICIPANT}),
    "chat": frozenset({Role.HOST, Role.MODERATOR, Role.PARTICIPANT}),
    "reaction": frozenset({Role.HOST, Role.MODERATOR, Role.PARTICIPANT}),
}

# Wire message type -> action; the router checks this before dispatch.
ACTION_BY_TYPE: dict[str, str] = {
    "play": "play",
    "pause": "pause",
    "seek": "seek",
    "change_video": "change_video",
    "assign_role": "assign_role",
    "remove_participant": "remove_participant",
    "transfer_host": "transfer_host",
    "lock_room": "lock_room",
    "request_action": "request_action",
    "resolve_request": "resolve_request",
    "chat": "chat",
    "reaction": "reaction",
}


def can(role: Role, action: str) -> bool:
    return role in _PERMISSIONS.get(action, frozenset())


def can_assign(actor: Role, target: Role, new_role: Role) -> bool:
    """Only the Host assigns, never to `host`, and never onto a Host target
    (which also blocks the Host assigning to themselves)."""
    if actor is not Role.HOST:
        return False
    if new_role not in (Role.MODERATOR, Role.PARTICIPANT):
        return False
    return target is not Role.HOST


def can_remove(actor: Role, target: Role) -> bool:
    """Only the Host removes, and nobody removes a Host (self-removal is the
    Host acting on their own Host role, so it is blocked here too)."""
    return actor is Role.HOST and target is not Role.HOST


def can_transfer(actor: Role, target: Role) -> bool:
    """Only the Host transfers; the target must not currently be Host."""
    return actor is Role.HOST and target is not Role.HOST
