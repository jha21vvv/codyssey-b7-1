import time
from pathlib import Path
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.database import Base, engine, get_db
from app.core.errors import register_error_handlers
from app.core.logger import logger, LoggingMiddleware
from app.core.migrations import upgrade_schema
from app.core.timeutil import utc_now
from app.models.user import User  # noqa: F401
from app.models.chat_log import ChatLog  # noqa: F401
from app.models.request_log import RequestLog  # noqa: F401
from app.services.ai_service import is_ai_configured
from app.services.request_log_service import record_request

"""
[안재현 전담] FastAPI 메인 애플리케이션 엔트리포인트
공통 미들웨어 등록, DB 테이블 초기화, 추후 팀원들의 라우터를 통합하는 중심 허브입니다.
"""

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 애플리케이션 시작 시 DB 테이블 자동 생성 (Base 상속 모델들)
    logger.info(f"[{settings.PROJECT_NAME}] 애플리케이션 시작 중... DB 테이블 점검")
    Base.metadata.create_all(bind=engine)
    upgrade_schema(engine)  # [권태현] 이전 버전으로 만든 DB에 새 컬럼 추가
    logger.info("DB 초기화 완료")
    yield
    logger.info(f"[{settings.PROJECT_NAME}] 애플리케이션 종료")

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="FastAPI 기반 지능형 웹 AI 챗봇 서비스 (Codyssey B7-1)",
    version="1.1.0",
    lifespan=lifespan
)

# 1. 공통 로깅 미들웨어 등록 (요청 수신 및 응답 추적)
# [권태현] API 요청은 요청 로그(DB request_logs)에도 한 줄씩 저장
app.add_middleware(LoggingMiddleware, on_request=record_request)

# 2. CORS 미들웨어 등록 (로컬 개발 및 외부 배포 도메인 통신 지원)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# [권태현] 모든 오류를 {detail, code, request_id} 공통 형식으로 응답 (app/core/errors.py)
register_error_handlers(app)

# 3. 헬스체크 엔드포인트 (서버 정상 작동 검증용)
APP_STARTED_AT = time.time()

@app.get("/health", tags=["Health"])
def health_check(db: Session = Depends(get_db)):
    """
    서버 및 인프라 상태 점검 엔드포인트
    [권태현] DB에 실제로 질의해 연결을 확인하고, 실패하면 503을 돌려줘
    외부 모니터링(Cloudflare Health Check 등)이 장애를 알아챌 수 있게 함
    """
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as e:
        db_status = "error"
        logger.error(f"[헬스체크 실패] DB 연결 오류: {type(e).__name__}")
    healthy = db_status == "ok"
    body = {
        "status": "healthy" if healthy else "unhealthy",
        "project": settings.PROJECT_NAME,
        "version": app.version,
        "uptime_seconds": int(time.time() - APP_STARTED_AT),
        "checked_at": utc_now().isoformat(timespec="seconds") + "Z",
        "database": {"status": db_status, "file": settings.DATABASE_URL.split("///")[-1]},
        "ai": {"configured": is_ai_configured()},  # 키 값은 보내지 않고 설정 여부만
    }
    return JSONResponse(status_code=200 if healthy else 503, content=body)

# 4. 웹 UI 화면 서빙 [권태현] (정적 파일 /static, 챗봇 화면 GET /, 관리자 화면 GET /admin)
# 서버를 실행한 폴더와 상관없이 파일을 찾도록 저장소 루트 기준 경로 사용
BASE_DIR = Path(__file__).resolve().parent.parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

@app.get("/", include_in_schema=False)
async def index(request: Request):
    """챗봇 웹 화면 (API가 아니라서 Swagger 문서에는 표시하지 않음)"""
    return templates.TemplateResponse(request, "index.html")

@app.get("/admin", include_in_schema=False)
async def admin_page(request: Request):
    """
    [권태현] 운영 관리자 화면
    화면 파일에는 데이터가 없고, 데이터는 관리자 API(/api/admin)가 관리자 계정인지 확인한 뒤에만 보냄
    """
    return templates.TemplateResponse(request, "admin.html")

# -------------------------------------------------------------
# [팀원 라우터 연동 슬롯]
# Phase 2 ~ 3에서 팀원들이 작성한 라우터를 아래에 include 합니다.
# -------------------------------------------------------------
from app.api.auth_router import router as auth_router  # [신재은]
from app.api.chat_router import router as chat_router  # [조명환]
from app.api.log_router import router as log_router    # [권태현]
from app.api.admin_router import router as admin_router  # [권태현] 관리자 API
#
app.include_router(auth_router, prefix="/api/auth", tags=["Auth"])
app.include_router(chat_router, prefix="/api/chat", tags=["Chat"])
app.include_router(log_router, prefix="/api/logs", tags=["Logs"])
app.include_router(admin_router, prefix="/api/admin", tags=["Admin"])
# -------------------------------------------------------------
