from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from services import auth_service


@dataclass(frozen=True)
class InteractionPolicy:
    actor_role: str
    can_affect_moral: bool
    can_affect_global_memory: bool


def resolve_interaction_policy(actor_user_uuid: Optional[str]) -> InteractionPolicy:
    role = "anonymous"
    if actor_user_uuid:
        try:
            user = auth_service.get_user_by_uuid(actor_user_uuid)
            if user and user.role:
                role = str(user.role).strip().lower()
        except Exception:
            role = "anonymous"

    is_owner = role == "owner"
    return InteractionPolicy(
        actor_role=role,
        can_affect_moral=is_owner,
        can_affect_global_memory=is_owner,
    )


def resolve_actor_uuid_from_auth_header(authorization: Optional[str]) -> Optional[str]:
    auth_header = (authorization or "").strip()
    if not auth_header:
        return None
    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    if not token:
        return None
    try:
        user = auth_service.get_user_from_access_token(token)
    except Exception:
        return None
    return user.uuid if user else None


def resolve_interaction_policy_from_auth_header(
    authorization: Optional[str],
) -> InteractionPolicy:
    actor_user_uuid = resolve_actor_uuid_from_auth_header(authorization)
    return resolve_interaction_policy(actor_user_uuid)
