import json
import asyncio
from typing import Dict, List, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(prefix="/ws", tags=["Real-time WebSockets"])

_MAIN_EVENT_LOOP: Optional[asyncio.AbstractEventLoop] = None


class ConnectionManager:
    """Each socket remembers which charities its user may see (None = all). An event naming a charity goes only
    to users of that charity; an event without one goes out with its details removed (the UI only needs the
    event name to refresh)."""
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.allowed: Dict[WebSocket, Optional[set]] = {}

    async def connect(self, websocket: WebSocket, allowed: Optional[set] = None):
        await websocket.accept()
        self.active_connections.append(websocket)
        self.allowed[websocket] = allowed
        print(f"[WebSocket] Client connected. Active clients: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.allowed.pop(websocket, None)
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            print(f"[WebSocket] Client disconnected. Active clients: {len(self.active_connections)}")

    async def broadcast(self, event_type: str, data: dict):
        comp = str((data or {}).get("company_id") or "").strip().lower()
        full = json.dumps({"event": event_type, "data": data})
        bare = json.dumps({"event": event_type, "data": {}})
        disconnected = []
        for connection in list(self.active_connections):
            allowed = self.allowed.get(connection)
            if comp and comp != "all" and allowed is not None and comp not in allowed:
                continue  # another charity's event
            payload = full if comp and (comp != "all" or allowed is None) else bare
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
    # Live events carry donation/expense details: only signed-in sessions may listen.
    # Browsers can't set headers on a WebSocket, so the session token comes as ?token=.
    from core.auth import user_from_token
    from backend.api.auth import user_company_ids
    user = user_from_token(websocket.query_params.get("token"))
    if not user:
        await websocket.close(code=1008)
        return
    await manager.connect(websocket, user_company_ids(user))
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
