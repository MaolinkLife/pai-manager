from typing import List
from fastapi import WebSocket


class ConnectionManager:
    """Open sockets. System events go to the owner's sockets only.

    Voice state, initiative messages, media updates, reminders and model pulls
    belong to the owner: a guest who came through a
    shared link gets only the replies to their own messages, which the chat
    route sends on their socket directly.
    """

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self._owner_sockets: set[int] = set()

    async def connect(self, websocket: WebSocket, *, owner: bool = False):
        await websocket.accept()
        self.active_connections.append(websocket)
        if owner:
            self._owner_sockets.add(id(websocket))

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        self._owner_sockets.discard(id(websocket))

    def is_owner(self, websocket: WebSocket) -> bool:
        return id(websocket) in self._owner_sockets

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
