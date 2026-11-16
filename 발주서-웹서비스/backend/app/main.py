"""발주서 웹서비스 FastAPI 앱 — 앱 생성·미들웨어·라우터 등록·SPA 정적 파일.

발주서·송장 라우트는 app/routes/process_fruit.py · process_goguma.py · process_sabang.py,
공용 헬퍼(엑셀 응답·이전 발주분 제외·프록시)는 app/api_common.py (2026-11-17 분리, 동작 변경 없음).
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.auth import router as auth_router, require_pro
from app.routes.dashboard import router as dashboard_router
from app.routes.products import router as products_router
from app.routes.pricing import router as pricing_router
from app.routes.toss import router as toss_router
from app.routes.admin import router as admin_router
from app.routes.tenant import router as tenant_router
from app.routes.billing import router as billing_router
from app.routes.automation import router as automation_router
from app.routes.rules import router as rules_router
from app.routes import process_fruit, process_goguma, process_sabang
from app.middleware import IPBlockMiddleware
from app import db as database
from app.scheduler import start_scheduler, stop_scheduler, refresh_products, refresh_orders

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await database.init_db()
    try:
        from app import rules_engine
        await rules_engine.refresh_rules()
    except Exception as e:
        # 캐시 미로드 시 프로세서들은 하드코딩 폴백으로 동작 — 발주 기능은 영향 없음
        logger.warning(f"규칙 엔진 초기 로드 실패(하드코딩 폴백으로 계속): {e}")
    start_scheduler()
    # Initial data load
    try:
        await refresh_products()
        await refresh_orders()
    except Exception as e:
        logger.warning(f"Initial data load failed (API keys may not be set): {e}")
    yield
    # Shutdown
    stop_scheduler()
    await database.close_db()


app = FastAPI(title="발주서 웹서비스 API", version="3.0.0", lifespan=lifespan)

# Middleware (order matters: IP block runs first)
app.add_middleware(IPBlockMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(tenant_router)
app.include_router(billing_router)
app.include_router(automation_router)
app.include_router(rules_router)
app.include_router(dashboard_router, dependencies=[Depends(require_pro)])
app.include_router(products_router, dependencies=[Depends(require_pro)])
app.include_router(pricing_router, dependencies=[Depends(require_pro)])
app.include_router(toss_router, dependencies=[Depends(require_pro)])


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}


# 발주서·송장 라우트(2026-11-17 main.py에서 분리) — 분리 전과 같은 등록 순서(health 다음, SPA 앞)
app.include_router(process_fruit.router)
app.include_router(process_goguma.router)
app.include_router(process_sabang.router)


# Serve frontend static files with SPA fallback
FRONTEND_DIR = Path(__file__).parent.parent / "static"
if FRONTEND_DIR.exists():
    from fastapi.responses import FileResponse

    FRONTEND_ROOT = FRONTEND_DIR.resolve()

    # Mount static assets (js, css, images)
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve index.html for all non-API routes (SPA fallback)."""
        if full_path.startswith("api/"):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

        index_path = FRONTEND_ROOT / "index.html"
        try:
            file_path = (FRONTEND_ROOT / full_path).resolve()
            file_path.relative_to(FRONTEND_ROOT)
        except ValueError:
            return FileResponse(str(index_path))

        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(index_path))
