"""Host tools: assign_role, remove_participant, transfer_host, lock_room (9, 8.2).

Permission is checked by the MessageRouter before these run; the handlers
re-check under the room lock because state can change between the check and the
mutation (D-13).
"""

from typing import TYPE_CHECKING, Any
from uuid import UUID

from watch_party.db.engine import SessionLocal
from watch_party.domain import permissions
from watch_party.domain.roles import Role
from watch_party.repositories import members as member_repo
from watch_party.repositories import rooms as room_repo

if TYPE_CHECKING:
    from watch_party.ws.endpoint import Connection

_ASSIGNABLE_ROLES = ("moderator", "participant")


def _target_id(payload: dict[str, Any]) -> str | None:
    target_id = payload.get("userId")
    return target_id if isinstance(target_id, str) else None


async def handle_assign_role(
    connection: "Connection", payload: dict[str, Any], request_id: str | None
) -> None:
    room, you = connection.room, connection.you
    if room is None or you is None:
        await connection.reject("not_found", "Not in a room.")
        return

    new_role_name = payload.get("role")
    if new_role_name not in _ASSIGNABLE_ROLES:
        await connection.reject("invalid_role", "Role must be moderator or participant.")
        return
    target_id = _target_id(payload)
    if target_id is None:
        await connection.reject("invalid_message", "Missing userId.")
        return
    if target_id == you.user_id:
        await connection.reject("forbidden", "You cannot assign a role to yourself.")
        return

    async with room.lock:
        target = room.participants.get(target_id)
        if target is None:
            await connection.reject("not_found", "Participant is not in this room.")
            return
        if not permissions.can_assign(you.role, target.role, Role(new_role_name)):
            await connection.reject("forbidden", "Your role cannot perform this action.")
            return
        target.role = Role(new_role_name)
        async with SessionLocal() as session:
            await connection.run_db(
                member_repo.update_role(session, room.require_db_id(), UUID(target_id), Role(new_role_name))
            )

    await room.broadcast(
        {
            "type": "role_assigned",
            "payload": {
                "userId": target_id,
                "username": target.username,
                "role": new_role_name,
                "participants": room.participant_snapshots(),
            },
        }
    )


async def handle_remove_participant(
    connection: "Connection", payload: dict[str, Any], request_id: str | None
) -> None:
    room, you = connection.room, connection.you
    if room is None or you is None:
        await connection.reject("not_found", "Not in a room.")
        return

    target_id = _target_id(payload)
    if target_id is None:
        await connection.reject("invalid_message", "Missing userId.")
        return
    if target_id == you.user_id:
        await connection.reject("forbidden", "You cannot remove yourself.")
        return

    async with room.lock:
        target = room.participants.get(target_id)
        if target is None:
            await connection.reject("not_found", "Participant is not in this room.")
            return
        if not permissions.can_remove(you.role, target.role):
            await connection.reject("forbidden", "Your role cannot perform this action.")
            return
        # Removed users are banned from the room (D-16).
        async with SessionLocal() as session:
            await connection.run_db(member_repo.ban_member(session, room.require_db_id(), UUID(target_id)))
        removed_connection = target.connection
        target.connection = None
        room.remove(target_id)
        # Snapshot AFTER removal, otherwise the broadcast still lists the
        # participant who was just removed and the client sees no change.
        participants = room.participant_snapshots()

    # 8.3: everyone still in the room hears it, then the removed user's socket
    # closes 4003. The removed user is sent to explicitly: they are no longer in
    # room.participants, so the room broadcast skips them.
    event = {
        "type": "participant_removed",
        "payload": {"userId": target_id, "participants": participants},
    }
    await room.broadcast(event)
    if removed_connection is not None:
        await removed_connection.send(event)
        await removed_connection.close(4003)

    if removed_connection is not None:
        await removed_connection.close(4003)


async def handle_transfer_host(
    connection: "Connection", payload: dict[str, Any], request_id: str | None
) -> None:
    room, you = connection.room, connection.you
    if room is None or you is None:
        await connection.reject("not_found", "Not in a room.")
        return

    target_id = _target_id(payload)
    if target_id is None:
        await connection.reject("invalid_message", "Missing userId.")
        return
    if target_id == you.user_id:
        await connection.reject("forbidden", "You cannot transfer host to yourself.")
        return

    async with room.lock:
        target = room.participants.get(target_id)
        if target is None:
            await connection.reject("not_found", "Participant is not in this room.")
            return
        if not target.online:
            await connection.reject("conflict", "Target must be online.")
            return
        if not permissions.can_transfer(you.role, target.role):
            await connection.reject("forbidden", "Your role cannot perform this action.")
            return

        previous_host_id = room.host_user_id
        target.role = Role.HOST
        room.host_user_id = target.user_id
        you.role = Role.MODERATOR
        async with SessionLocal() as session:
            await connection.run_db(room_repo.set_room_host(session, room.require_db_id(), UUID(target.user_id)))
            await connection.run_db(
                member_repo.update_role(session, room.require_db_id(), UUID(target.user_id), Role.HOST)
            )
            await connection.run_db(
                member_repo.update_role(session, room.require_db_id(), UUID(you.user_id), Role.MODERATOR)
            )
        participants_snapshot = room.participant_snapshots()

    # 8.3: host_transferred + role_assigned for both changed users.
    await room.broadcast(
        {
            "type": "host_transferred",
            "payload": {
                "oldHostId": previous_host_id,
                "newHostId": target.user_id,
                "participants": participants_snapshot,
            },
        }
    )
    for user, role in ((target, Role.HOST), (you, Role.MODERATOR)):
        await room.broadcast(
            {
                "type": "role_assigned",
                "payload": {
                    "userId": user.user_id,
                    "username": user.username,
                    "role": role.value,
                    "participants": participants_snapshot,
                },
            }
        )


async def handle_lock_room(
    connection: "Connection", payload: dict[str, Any], request_id: str | None
) -> None:
    room, you = connection.room, connection.you
    if room is None or you is None:
        await connection.reject("not_found", "Not in a room.")
        return

    locked = bool(payload.get("locked"))
    async with room.lock:
        room.locked = locked
        async with SessionLocal() as session:
            await connection.run_db(
                room_repo.set_room_status(
                    session, room.require_db_id(), "locked" if locked else "open"
                )
            )

    await room.broadcast({"type": "room_locked", "payload": {"locked": locked}})


async def reassign_host(connection: "Connection") -> None:
    """10.4: promote the longest-tenured online Moderator, else the longest-tenured
    online Participant. With nobody online the room simply sits empty."""
    room = connection.room
    if room is None:
        return

    async with room.lock:
        previous_host_id = room.host_user_id
        current_host = room.participants.get(previous_host_id)
        if current_host is not None and current_host.online:
            return  # the host came back (grace cancelled elsewhere)
        online = sorted(
            (participant for participant in room if participant.online),
            key=lambda participant: participant.joined_at,
        )
        candidates = [p for p in online if p.role == Role.MODERATOR] or [
            p for p in online if p.role == Role.PARTICIPANT
        ]
        if not candidates:
            return

        new_host = candidates[0]
        new_host.role = Role.HOST
        room.host_user_id = new_host.user_id
        if current_host is not None:
            current_host.role = Role.MODERATOR
        async with SessionLocal() as session:
            await connection.run_db(
                room_repo.set_room_host(session, room.require_db_id(), UUID(new_host.user_id))
            )
            if current_host is not None:
                await connection.run_db(
                    member_repo.update_role(
                        session, room.require_db_id(), UUID(current_host.user_id), Role.MODERATOR
                    )
                )
            await connection.run_db(
                member_repo.update_role(session, room.require_db_id(), UUID(new_host.user_id), Role.HOST)
            )
        participants_snapshot = room.participant_snapshots()
        events = [
            {
                "type": "host_transferred",
                "payload": {
                    "oldHostId": previous_host_id,
                    "newHostId": new_host.user_id,
                    "participants": participants_snapshot,
                },
            }
        ]
        events.append(
            {
                "type": "role_assigned",
                "payload": {
                    "userId": new_host.user_id,
                    "username": new_host.username,
                    "role": "host",
                    "participants": participants_snapshot,
                },
            }
        )
        if current_host is not None:
            events.append(
                {
                    "type": "role_assigned",
                    "payload": {
                        "userId": current_host.user_id,
                        "username": current_host.username,
                        "role": "moderator",
                        "participants": participants_snapshot,
                    },
                }
            )

    for event in events:
        await room.broadcast(event)
