from datetime import datetime
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import Settings
from .schemas import (
    DecisionPage,
    Health,
    Overview,
    Performance,
    ReasonCatalogEntry,
    ResolutionPage,
    Telemetry,
)
from .services import REASON_CATALOG, Monitor


def create_app(settings=None):
    app = FastAPI(
        title="PolyBTC v2 · Read-only monitor", version="1.0.0", docs_url="/api/docs", redoc_url=None
    )
    monitor = Monitor(settings or Settings.load())
    app.state.monitor = monitor
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"])
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_methods=["GET"],
        allow_headers=["Accept"],
    )

    @app.middleware("http")
    async def read_only(request: Request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            from starlette.responses import JSONResponse

            return JSONResponse({"detail": "Monitoring API is read-only."}, status_code=405)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/api/overview", response_model=Overview)
    def overview(minutes: int = Query(15, ge=1, le=60)):
        return monitor.overview(minutes)

    @app.get("/api/market", response_model=Telemetry)
    @app.get("/api/telemetry", response_model=Telemetry)
    def market(minutes: int = Query(15, ge=1, le=60)):
        return monitor.telemetry(minutes)

    @app.get("/api/decisions", response_model=DecisionPage)
    @app.get("/api/predictions", response_model=DecisionPage)
    def decisions(
        page: int = Query(1, ge=1, le=10000),
        page_size: int = Query(25, ge=1, le=100),
        search: str = Query("", max_length=200),
        market: str = Query("", max_length=200),
        horizon: int | None = None,
        reason: str = Query("", max_length=150),
        status: str = Query("", max_length=50),
        availability: Literal["all", "available", "missing"] = "all",
        outcome: Literal["all", "verified", "missing"] = "all",
        minimum: float | None = Query(None, ge=0, le=1),
        maximum: float | None = Query(None, ge=0, le=1),
        after: datetime | None = None,
        before: datetime | None = None,
        sort: Literal[
            "target_at_utc", "horizon_seconds", "model_probability_yes", "status", "reason"
        ] = "target_at_utc",
        direction: Literal["asc", "desc"] = "desc",
    ):
        if horizon is not None and horizon not in (240, 180, 120, 90, 60, 30):
            raise HTTPException(422, "Unsupported horizon")
        if any(t is not None and t.tzinfo is None for t in (after, before)):
            raise HTTPException(422, "Time filters require an explicit timezone")
        if (minimum is not None and maximum is not None and minimum > maximum) or (
            after and before and after > before
        ):
            raise HTTPException(422, "Filter range is inverted")
        arguments = locals().copy()
        arguments.pop("monitor", None)
        return monitor.decisions(**arguments)

    @app.get("/api/resolutions", response_model=ResolutionPage)
    def resolutions():
        return monitor.resolutions()

    @app.get("/api/performance", response_model=Performance)
    def performance():
        return monitor.performance()

    @app.get("/api/health", response_model=Health)
    def health():
        return monitor.health()

    @app.get("/api/settings")
    def dashboard_settings():
        return {
            "paths": {
                k: str(getattr(monitor.settings, k))
                for k in ("telemetry", "decisions", "trades", "resolutions", "report")
            },
            "path_editing": "Edit dashboard/config.toml and restart the dashboard backend. Paths cannot be changed by API requests.",
            "read_only": True,
            "reference_max_age_ms": 3000,
            "book_max_age_ms": 500,
            "operational_controls": "Not implemented. No process or trading command endpoints exist.",
        }

    @app.get("/api/reasons", response_model=dict[str, ReasonCatalogEntry])
    def reasons():
        return REASON_CATALOG

    return app


app = create_app()
