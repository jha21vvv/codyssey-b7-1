from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager
from app.core.config import settings
from app.core.database import Base, engine
from app.core.logger import logger, LoggingMiddleware

"""
[안재현 전담] FastAPI 메인 애플리케이션 엔트리포인트
공통 미들웨어 등록, DB 테이블 초기화, 추후 팀원들의 라우터를 통합하는 중심 허브입니다.
"""

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 애플리케이션 시작 시 DB 테이블 자동 생성 (Base 상속 모델들)
    logger.info(f"[{settings.PROJECT_NAME}] 애플리케이션 시작 중... DB 테이블 점검")
    Base.metadata.create_all(bind=engine)
    logger.info("DB 초기화 완료")
    yield
    logger.info(f"[{settings.PROJECT_NAME}] 애플리케이션 종료")

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="FastAPI 기반 지능형 웹 AI 챗봇 서비스 (Codyssey B7-1)",
    version="1.0.0",
    lifespan=lifespan
)

# 1. 공통 로깅 미들웨어 등록 (요청 수신 및 응답 추적)
app.add_middleware(LoggingMiddleware)

# 2. CORS 미들웨어 등록 (로컬 개발 및 외부 배포 도메인 통신 지원)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 3. 헬스체크 엔드포인트 (서버 정상 작동 검증용)
@app.get("/health", tags=["Health"])
async def health_check():
    """서버 및 인프라 상태 점검 엔드포인트"""
    return {
        "status": "healthy",
        "project": settings.PROJECT_NAME,
        "database": settings.DATABASE_URL.split("///")[-1]
    }

# 4. 웹 UI 화면 서빙 [권태현] (정적 파일 /static, 챗봇 화면 GET /)
# 서버를 실행한 폴더와 상관없이 파일을 찾도록 저장소 루트 기준 경로 사용
BASE_DIR = Path(__file__).resolve().parent.parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

@app.get("/", include_in_schema=False)
async def index(request: Request):
    """챗봇 웹 화면 (API가 아니라서 Swagger 문서에는 표시하지 않음)"""
    return templates.TemplateResponse(request, "index.html")

# -------------------------------------------------------------
# [팀원 라우터 연동 슬롯]
# Phase 2 ~ 3에서 팀원들이 작성한 라우터를 아래에 include 합니다.
# -------------------------------------------------------------
from app.api.auth_router import router as auth_router  # [신재은]
from app.api.chat_router import router as chat_router  # [조명환]
from app.api.log_router import router as log_router    # [권태현]
#
app.include_router(auth_router, prefix="/api/auth", tags=["Auth"])
app.include_router(chat_router, prefix="/api/chat", tags=["Chat"])
app.include_router(log_router, prefix="/api/logs", tags=["Logs"])
# -------------------------------------------------------------
