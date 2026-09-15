from typing import Dict, List, Optional
from fastapi import WebSocket


class ConnectionManager:
    """Open sockets. System events go to the owner's sockets only.

    Voice state, initiative messages, media updates, reminders and model pulls
    belong to the owner: a guest who came through a
    shared link gets only the replies to their own messages, which the chat
    route sends on their socket directly.

    A socket opened with a session token is also known by its user, so a chat
    run whose own socket dropped can reach the same user on a newer one
    (core.ws_runs). A socket without a token belongs to nobody.
    """

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self._owner_sockets: set[int] = set()
        self._user_sockets: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, *, owner: bool = False, user_uuid: Optional[str] = None):
        await websocket.accept()
        self.active_connections.append(websocket)
        if owner:
            self._owner_sockets.add(id(websocket))
        if user_uuid:
            self._user_sockets.setdefault(user_uuid, []).append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections = [socket for socket in self.active_connections if socket is not websocket]
        self._owner_sockets.discard(id(websocket))
        for user_uuid in list(self._user_sockets):
            remaining = [socket for socket in self._user_sockets[user_uuid] if socket is not websocket]
            if remaining:
                self._user_sockets[user_uuid] = remaining
            else:
                del self._user_sockets[user_uuid]

    def is_owner(self, websocket: WebSocket) -> bool:
        return id(websocket) in self._owner_sockets

    def sockets_for_user(self, user_uuid: Optional[str]) -> List[WebSocket]:
        """The user's live sockets, newest first; none without a token user."""
        if not user_uuid:
            return []
        return list(reversed(self._user_sockets.get(user_uuid, [])))

    async def send_message(self, message: str):
        for connection in list(self.active_connections):
            if not self.is_owner(connection):
                continue
            try:
                await connection.send_text(message)
            except Exception:
                # We don't throw the error so as not to break other clients
                self.disconnect(connection)


# Global instance of the connection manager
manager = ConnectionManager()
