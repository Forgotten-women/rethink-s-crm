"""
Live "data changed" notifications (Server-Sent Events).

The data-version token (core.cache.version_token) changes the moment any process - an API worker, the
platform-sync service, a script - writes data, because SQLite triggers / file fingerprints drive it. One small
watcher per worker process checks the token of each charity that has a listener once a second and pushes
changes to every open tab of that charity. Browsers can't add headers to an EventSource, so the session token
is passed as ?token= (same as the WebSocket). Each user only ever subscribes to a charity they may access.

The same stream tells the tab when the user's ACCESS changes (RBAC, core/rbac.py): every few seconds it
compares the account's access stamp; on a change it sends `event: access` so the page re-reads /api/auth/me and
shows/hides tabs and buttons at once. A disabled account, a "sign out everywhere", or losing this charity ends the
stream with `{"signed_out": true}` / `{"lost_company": true}`.
"""
import asyncio
import json
from typing import Dict, Optional, Set

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from backend.api.auth import require_company_access
from core.auth import user_from_token
from core.rbac import access_stamp
from core.cache import version_token

router = APIRouter(prefix="/api/stream", tags=["Live updates"])

SCOPES = ["donations", "classification", "tracker", "payouts", "fundraisers", "expenses"]
POLL_SECONDS = 1.0
HEARTBEAT_SECONDS = 15.0
ACCESS_CHECK_SECONDS = 3.0

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
    user = user_from_token(token)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session token has expired or is invalid.")
    comp = require_company_access(user, company_id or "rethink")

    queue: asyncio.Queue = asyncio.Queue(maxsize=1)
    _listeners.setdefault(comp, set()).add(queue)
    _ensure_watcher()

    async def events():
        try:
            current = _latest.get(comp) or await asyncio.to_thread(version_token, SCOPES, comp)
            _latest.setdefault(comp, current)  # the watcher then only pushes real changes
            yield f"retry: 5000\nevent: version\ndata: {json.dumps({'company_id': comp, 'token': current})}\n\n"
            stamp = await asyncio.to_thread(access_stamp, user["id"])
            quiet = 0.0
            while True:
                if await request.is_disconnected():
                    break
                try:
                    new_token = await asyncio.wait_for(queue.get(), timeout=ACCESS_CHECK_SECONDS)
                    yield f"event: version\ndata: {json.dumps({'company_id': comp, 'token': new_token})}\n\n"
                    quiet = 0.0
                except asyncio.TimeoutError:
                    quiet += ACCESS_CHECK_SECONDS
                    if quiet >= HEARTBEAT_SECONDS:
                        yield ": keep-alive\n\n"
                        quiet = 0.0
                new_stamp = await asyncio.to_thread(access_stamp, user["id"])
                if new_stamp != stamp:
                    stamp = new_stamp
                    now_user = await asyncio.to_thread(user_from_token, token)
                    if not now_user:
                        yield f"event: access\ndata: {json.dumps({'signed_out': True})}\n\n"
                        break
                    try:
                        require_company_access(now_user, comp)
                        allowed = True
                    except HTTPException:
                        allowed = False
                    yield f"event: access\ndata: {json.dumps({'changed': True, 'lost_company': not allowed})}\n\n"
                    if not allowed:
                        break
        finally:
            _listeners.get(comp, set()).discard(queue)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
