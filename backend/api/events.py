import json
import asyncio
from typing import List, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(prefix="/ws", tags=["Real-time WebSockets"])

_MAIN_EVENT_LOOP: Optional[asyncio.AbstractEventLoop] = None


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"[WebSocket] Client connected. Active clients: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            print(f"[WebSocket] Client disconnected. Active clients: {len(self.active_connections)}")

    async def broadcast(self, event_type: str, data: dict):
        payload = json.dumps({"event": event_type, "data": data})
        disconnected = []
        for connection in list(self.active_connections):
            try:
                await connection.send_text(payload)
            except Exception:
                disconnected.append(connection)
        for conn in disconnected:
            self.disconnect(conn)


manager = ConnectionManager()


def set_main_event_loop(loop: asyncio.AbstractEventLoop):
    """Stores the main server event loop for thread-safe cross-thread dispatching."""
    global _MAIN_EVENT_LOOP
    _MAIN_EVENT_LOOP = loop


@router.websocket("/events")
async def websocket_events_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive with heartbeat ping
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text(json.dumps({"event": "pong"}))
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)


def broadcast_event_sync(event_type: str, data: dict):
    """
    Synchronous wrapper to safely broadcast events to all WebSocket clients
    from synchronous routes or AnyIO worker threads without loop errors.
    """
    global _MAIN_EVENT_LOOP
    try:
        # 1. Main loop thread-safe dispatch (works from AnyIO background threads)
        if _MAIN_EVENT_LOOP and _MAIN_EVENT_LOOP.is_running():
            asyncio.run_coroutine_threadsafe(manager.broadcast(event_type, data), _MAIN_EVENT_LOOP)
            return

        # 2. Local running loop fallback
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                loop.create_task(manager.broadcast(event_type, data))
                return
        except RuntimeError:
            pass
    except Exception as e:
        print(f"[WebSocket Broadcast Notice]: {e}")
