from typing import Any, Dict
from fastapi import FastAPI
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.logger import logger
from app.models.request_log import RequestLog

"""
[권태현 전담] 요청 로그 저장 서비스
LoggingMiddleware가 API 요청을 마칠 때마다 record_request를 불러 request_logs에 한 줄씩 저장합니다.
"""

def save_request_log(db: Session, **fields: Any) -> RequestLog:
    """요청 로그 한 줄 저장 (실패하면 롤백 후 예외를 다시 올림)"""
    log = RequestLog(**fields)
    try:
        db.add(log)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return log

def record_request(app: FastAPI, fields: Dict[str, Any]) -> None:
    """
    미들웨어에서 부르는 저장 함수
    테스트처럼 get_db를 바꿔 끼운 경우에도 같은 DB에 저장되도록 앱의 의존성 교체를 따르고,
    저장에 실패해도 사용자 요청에는 영향을 주지 않도록 경고 로그만 남김
    """
    provider = app.dependency_overrides.get(get_db, get_db)
    db_gen = provider()
    try:
        save_request_log(next(db_gen), **fields)
    except Exception as e:
        logger.warning(f"[요청 로그 저장 실패] {type(e).__name__}")
    finally:
        db_gen.close()
