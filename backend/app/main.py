import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

from app import models  # noqa: F401  (registers tables)
from app.api.v1 import assist, auth, encounters, internal, org, packs, patients, referrals, reports
from app.core.config import get_settings
from app.core.db import Base, SessionLocal, engine
from app.core.storage import LocalStorage, get_storage
from app.modules.encounters.service import run_photo_retention
from app.modules.packs.loader import get_packs

log = logging.getLogger("scanassist")


async def _retention_loop(interval_minutes: int) -> None:
    while True:
        try:
            with SessionLocal() as db:
                result = await asyncio.to_thread(run_photo_retention, db, get_storage())
                if any(result.values()):
                    log.info("photo retention: %s", result)
        except Exception:
            log.exception("photo retention job failed")
        await asyncio.sleep(interval_minutes * 60)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.validate_for_runtime()
    packs_loaded = get_packs()  # fail fast on an invalid pack
    log.info("packs loaded: %s", ", ".join(packs_loaded))
    if settings.app_env != "production":
        Base.metadata.create_all(engine)  # production schema is created by scripts/init_db.py
    task = None
    if settings.app_env != "test":
        task = asyncio.create_task(_retention_loop(settings.photo_job_interval_minutes))
    yield
    if task:
        task.cancel()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="ScanAssist API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # assist = stateless mobile mode; the record-keeping routers below are parked (not used by the app).
    for r in (assist, auth, org, packs, patients, encounters, reports, referrals, internal):
        app.include_router(r.router, prefix="/v1")

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/v1/local-storage/{key:path}", include_in_schema=False)
    def local_storage(key: str, expires: int, sig: str) -> Response:
        """Serves signed URLs for the development storage backend only."""
        storage = get_storage()
        if not isinstance(storage, LocalStorage) or not storage.verify(key, expires, sig):
            raise HTTPException(403)
        if not storage.exists(key):
            raise HTTPException(404)
        return Response(storage.get(key), media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    return app


app = create_app()
