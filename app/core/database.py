from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from typing import Generator
from app.core.config import settings

"""
[안재현 전담] 데이터베이스 연결 및 세션 팩토리 모듈
신재은(User 모델)과 권태현(ChatLog 모델) 및 모든 API 라우터가 공유합니다.
"""

# SQLite 연결 설정 (멀티스레드 지원 옵션 포함)
connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    echo=False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# SQLAlchemy 모델 선언용 기본 클래스 (팀원들이 상속받아 모델 정의)
Base = declarative_base()

def get_db() -> Generator[Session, None, None]:
    """
    FastAPI 라우터 의존성 주입용 DB 세션 제너레이터
    요청 시 세션을 열고, 요청 완료 후 안전하게 세션을 닫습니다.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
