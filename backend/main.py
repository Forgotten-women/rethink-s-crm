import os
import sys
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.api import admin, auth, cache_versions, classifications, donors, events, expenses, filters, fundraisers, ltv, metrics, overview, ops, payouts, tracker, webhooks

app = FastAPI(
    title="Crowdfunding Analytics & Enterprise CRM API",
    description="High-performance FastAPI engine providing LTV analytics, 360° donor profiles, classification rules, and dataset management.",
    version="2.0.0"
)

# Enable CORS for React / Vercel frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://rethink-s-crm.vercel.app",
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8000",
        "https://rethink-s-crm-5e5c3bf8.fastapicloud.dev",
        "*"
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Compress JSON responses (the classification matrices are several MB uncompressed).
app.add_middleware(GZipMiddleware, minimum_size=1024)

# Audit trail: every change (POST/PUT/PATCH/DELETE), every server error and every denied request is
# recorded via core.event_log (local table + Axiom). Read-only traffic is not logged.
_AUDIT_SKIP_PREFIXES = ("/api/tracker/email-tracking/pixel/", "/api/tracker/outlook/webhook", "/api/ops/logs", "/ws/")


@app.middleware("http")
async def audit_log_middleware(request, call_next):
    import asyncio
    import time as _time
    from core.event_log import log_event
    from core.cache import current_request
    request_token = current_request.set(request)  # lets the response cache read ETag / nocache headers
    start = _time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        current_request.reset(request_token)
        path = request.url.path
        mutating = request.method in ("POST", "PUT", "PATCH", "DELETE")
        if path.startswith("/api/") and not path.startswith(_AUDIT_SKIP_PREFIXES) and (
                mutating or status_code >= 500 or status_code in (401, 403)):
            actor = None
            auth_hdr = request.headers.get("authorization", "")
            if auth_hdr.lower().startswith("bearer "):
                from core.auth import decode_access_token
                claims = decode_access_token(auth_hdr[7:].strip()) or {}
                actor = claims.get("sub")
            level = "error" if status_code >= 500 else ("warning" if status_code in (401, 403) else "info")
            category = "security" if status_code in (401, 403) else "audit"
            event = "http.denied" if status_code in (401, 403) else ("http.error" if status_code >= 500 else "http.change")
            await asyncio.to_thread(
                log_event, event, category=category, level=level,
                message=f"{request.method} {path} -> {status_code}",
                company_id=request.query_params.get("company_id"), actor=actor,
                method=request.method, path=path, status=status_code,
                duration_ms=round((_time.perf_counter() - start) * 1000),
                client_ip=request.headers.get("x-forwarded-for", request.client.host if request.client else None),
            )


# Register API Routers
app.include_router(ops.router)
app.include_router(cache_versions.router)
app.include_router(auth.router)
app.include_router(metrics.router)
app.include_router(overview.router)
app.include_router(ltv.router)
app.include_router(donors.router)
app.include_router(classifications.router)
app.include_router(admin.router)
app.include_router(expenses.router)
app.include_router(filters.router)
app.include_router(events.router)
app.include_router(tracker.router)
app.include_router(payouts.router)
app.include_router(fundraisers.router)
app.include_router(webhooks.router)

# Mount logos directory for branded email assets
logos_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data_cache", "logos")
if os.path.exists(logos_dir):
    app.mount("/logos", StaticFiles(directory=logos_dir), name="logos")


@app.get("/api/health", tags=["Health"])
@app.get("/health", tags=["Health"])
def health_check():
    return {
        "status": "healthy",
        "service": "Crowdfunding Enterprise CRM API",
        "version": "2.0.0"
    }


@app.get("/", tags=["Root"])
def root_endpoint():
    return {
        "status": "online",
        "service": "Crowdfunding Analytics & Enterprise CRM API",
        "version": "2.0.0",
        "docs": "/docs",
        "health": "/api/health"
    }


@app.on_event("startup")
async def startup_event():
    import asyncio
    from backend.api.events import set_main_event_loop
    try:
        set_main_event_loop(asyncio.get_running_loop())
    except Exception as loop_err:
        print(f"[WebSocket Loop Init Notice]: {loop_err}")

    print("Crowdfunding Enterprise CRM API initialized and ready to receive requests.")

    # 1. Cold-start restore: decrypt encrypted cache if plain parquet is not present
    try:
        from core.security import ensure_cache_decrypted
        ensure_cache_decrypted()
    except Exception as dec_err:
        print(f"[Cold-start Decrypt Notice]: {dec_err}")

    # 2. Seed database & build indexes if missing
    try:
        from core.database import seed_database_if_empty, ensure_database_indexes
        seed_database_if_empty()
        ensure_database_indexes()
    except Exception as e:
        print(f"[Startup Seed & Index Notice]: {e}")






    # 3. Response-cache invalidation: DB triggers bump data_versions on every write (any process).
    try:
        from core.cache import install_version_triggers
        created = await asyncio.to_thread(install_version_triggers)
        if created:
            print(f"[Cache] Installed {created} data-version triggers")
    except Exception as cache_err:
        print(f"[Cache Trigger Notice]: {cache_err}")

    # 4. Cache warm-up: rebuild the heaviest pages in the background after the data changes.
    asyncio.get_running_loop().create_task(_cache_warmup_loop())

    # 5. Daily sponsorship email-queue refresh: only creates PENDING items for staff to review;
    #    nothing is emailed until someone presses Send in the tracker's Email Queue.
    asyncio.get_running_loop().create_task(_sponsorship_queue_daily_loop())


async def _sponsorship_queue_daily_loop():
    import asyncio
    from backend.api.tracker import generate_email_queue
    await asyncio.sleep(120)  # let startup finish and the cache warm
    while True:
        for company in ("rethink", "iqra"):
            try:
                created = await asyncio.to_thread(generate_email_queue, company)
                print(f"[Sponsorship Queue] {company}: {created}")
            except Exception as queue_err:
                print(f"[Sponsorship Queue Notice] {company}: {queue_err}")
        await asyncio.sleep(24 * 60 * 60)


async def _cache_warmup_loop():
    """One worker (file lock) watches each company's donation/classification versions and, when they
    change (e.g. platform-sync ingested a donation), pre-computes the slowest endpoints so the next
    visitor gets a cached response. At most once per 5 minutes per company."""
    import asyncio
    import time as _time
    from core.cache import route_defaults, try_exclusive, version_token
    from core.event_log import log_event
    await asyncio.sleep(30)
    lock = try_exclusive("cache_warmup")
    if lock is None:
        return  # another worker is the warmer
    from backend.api import classifications, metrics, overview, tracker
    last_token, last_run = {}, {}
    jobs = {
        "rethink": [(classifications.get_launchgood_matrix, {}), (classifications.get_givebright_matrix, {}),
                    (metrics.get_metrics_summary, {}), (overview.get_overview_top_campaigns, {})]
                   + [(tracker.get_qualifying_donors, {"sponsorship_type": t}) for t in ("Orphan", "Widow", "Hafiz", "Ex-Prisoner")],
        "iqra": [(classifications.get_madinah_matrix, {}), (classifications.get_givebright_matrix, {}),
                 (metrics.get_metrics_summary, {}), (overview.get_overview_top_campaigns, {})]
                + [(tracker.get_qualifying_donors, {"sponsorship_type": t}) for t in ("Orphan", "Widow", "Hafiz", "Ex-Prisoner")],
    }
    while True:
        for company, fns in jobs.items():
            try:
                token = await asyncio.to_thread(version_token, ["donations", "classification", "tracker"], company)
                if token == last_token.get(company) or _time.time() - last_run.get(company, 0) < 300:
                    continue
                started = _time.perf_counter()
                for fn, extra in fns:
                    kwargs = route_defaults(fn, company_id=company, **extra)
                    await asyncio.to_thread(fn, **kwargs)
                last_token[company], last_run[company] = token, _time.time()
                log_event("cache.warmed", category="performance", company_id=company, endpoints=len(fns),
                          duration_ms=round((_time.perf_counter() - started) * 1000),
                          message=f"Pre-computed {len(fns)} heavy pages for {company}")
            except Exception as warm_err:
                print(f"[Cache Warm-up Notice] {company}: {warm_err}")
        await asyncio.sleep(60)
