from typing import Callable, Dict, List, Optional, Set
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

    Such a socket also knows its sign-in, so signing a device out closes the
    chat that device holds open.
    """

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self._owner_sockets: set[int] = set()
        self._user_sockets: Dict[str, List[WebSocket]] = {}
        self._sign_ins: Dict[int, str] = {}

    async def connect(
        self,
        websocket: WebSocket,
        *,
        owner: bool = False,
        user_uuid: Optional[str] = None,
        sign_in_id: Optional[str] = None,
    ):
        await websocket.accept()
        self.active_connections.append(websocket)
        if owner:
            self._owner_sockets.add(id(websocket))
        if user_uuid:
            self._user_sockets.setdefault(user_uuid, []).append(websocket)
        if sign_in_id:
            self._sign_ins[id(websocket)] = sign_in_id

    async def close_ended_sign_ins(self, live_sign_ins: Callable[[Set[str]], Set[str]], code: int) -> int:
        """Close the sockets whose sign-in has ended; returns how many were closed."""
        signed_in = set(self._sign_ins.values())
        if not signed_in:
            return 0
        live = live_sign_ins(signed_in)
        ended = [
            socket
            for socket in list(self.active_connections)
            if id(socket) in self._sign_ins and self._sign_ins[id(socket)] not in live
        ]
        for socket in ended:
            self.disconnect(socket)
            try:
                await socket.close(code=code)
            except Exception:
                # The socket dropped on its own meanwhile: nothing left to close.
                pass
        return len(ended)

    def disconnect(self, websocket: WebSocket):
        self.active_connections = [socket for socket in self.active_connections if socket is not websocket]
        self._owner_sockets.discard(id(websocket))
        self._sign_ins.pop(id(websocket), None)
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
