"""
Live "data changed" notifications (Server-Sent Events).

The data-version token (core.cache.version_token) changes the moment any process - an API worker, the
platform-sync service, a script - writes data, because SQLite triggers / file fingerprints drive it. One small
watcher per worker process checks the token of each charity that has a listener once a second and pushes
changes to every open tab of that charity. Browsers can't add headers to an EventSource, so the session token
is passed as ?token= (same as the WebSocket). Each user only ever subscribes to a charity they may access.
"""
import asyncio
import json
from typing import Dict, Optional, Set

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from backend.api.auth import _user_from_claims, require_company_access
from core.auth import decode_access_token, get_user_by_identity
from core.cache import version_token

router = APIRouter(prefix="/api/stream", tags=["Live updates"])

SCOPES = ["donations", "classification", "tracker", "payouts", "fundraisers", "expenses"]
POLL_SECONDS = 1.0
HEARTBEAT_SECONDS = 15.0

_listeners: Dict[str, Set[asyncio.Queue]] = {}
_latest: Dict[str, str] = {}
_watcher: Optional[asyncio.Task] = None


async def _watch() -> None:
    while True:
        for comp in [c for c, qs in _listeners.items() if qs]:
            try:
                token = await asyncio.to_thread(version_token, SCOPES, comp)
            except Exception:
                continue
            if token.startswith("err-") or token == _latest.get(comp):
                continue
            _latest[comp] = token
            for queue in list(_listeners.get(comp, ())):
                if queue.full():
                    queue.get_nowait()  # a slow tab only needs the newest token
                queue.put_nowait(token)
        await asyncio.sleep(POLL_SECONDS)


def _ensure_watcher() -> None:
    global _watcher
    if _watcher is None or _watcher.done():
        _watcher = asyncio.get_running_loop().create_task(_watch())


@router.get("/versions")
async def stream_versions(request: Request, company_id: Optional[str] = Query("rethink"), token: str = Query("")):
    claims = decode_access_token(token or "") or {}
    if not claims.get("sub"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session token has expired or is invalid.")
    user = get_user_by_identity(claims["sub"]) or _user_from_claims(claims)
    comp = require_company_access(user, company_id or "rethink")

    queue: asyncio.Queue = asyncio.Queue(maxsize=1)
    _listeners.setdefault(comp, set()).add(queue)
    _ensure_watcher()

    async def events():
        try:
            current = _latest.get(comp) or await asyncio.to_thread(version_token, SCOPES, comp)
            _latest.setdefault(comp, current)  # the watcher then only pushes real changes
            yield f"retry: 5000\nevent: version\ndata: {json.dumps({'company_id': comp, 'token': current})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    new_token = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                    yield f"event: version\ndata: {json.dumps({'company_id': comp, 'token': new_token})}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            _listeners.get(comp, set()).discard(queue)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
