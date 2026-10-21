from typing import List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.logger import logger
from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.chat_log import ChatLogResponse
from app.services.log_service import get_user_chat_logs

"""
[권태현 전담] 대화 로그 조회 API (main.py에서 prefix="/api/logs"로 연결)
- GET /api/logs/me : 로그인한 사용자 본인의 대화 이력 (최신순)
"""

router = APIRouter()

@router.get("/me", response_model=List[ChatLogResponse])
def read_my_logs(
    limit: int = Query(100, ge=1, le=500, description="가져올 최근 대화 수 (최대 500)"),
    current_user: User = Depends(get_current_user),  # 비로그인·만료 토큰은 401로 차단 (신재은 deps)
    db: Session = Depends(get_db),
):
    """[과제 요구사항: 사용자 기준 로그 조회] 내 대화 이력을 최신순으로 반환"""
    logs = get_user_chat_logs(user_id=current_user.id, limit=limit, db=db)
    logger.info(f"[대화 이력 조회] user_id={current_user.id}, 건수={len(logs)}")
    return logs
