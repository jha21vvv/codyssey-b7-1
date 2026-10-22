import secrets
from typing import List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.database import get_db
from app.core.logger import logger
from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.chat_log import ChatLogResponse
from app.services.log_service import get_user_chat_logs, get_all_chat_logs

"""
[권태현 전담] 대화 로그 조회 API (main.py에서 prefix="/api/logs"로 연결)
- GET /api/logs/me    : 로그인한 사용자 본인의 대화 이력 (최신순)
- GET /api/logs/admin : 관리자/평가자용 전체 대화 이력 (X-Admin-Key 헤더 필요)
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

# [안내서 대비 변경] 안내서에는 /admin 보호 방법이 없어, 누구나 모든 사용자의 대화를 볼 수 없도록 관리자 키 검사를 추가
def verify_admin_key(x_admin_key: Optional[str] = Header(None)) -> None:
    """
    .env의 ADMIN_API_KEY와 같은 값을 X-Admin-Key 헤더로 보내야 통과
    키를 설정하지 않으면 기능이 꺼져 있어, 배포 주소에서 다른 사람의 대화를 볼 수 없음
    """
    if not settings.ADMIN_API_KEY:
        logger.warning("[전체 로그 조회 거부] ADMIN_API_KEY가 설정되지 않아 기능이 꺼져 있음")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="전체 로그 조회 기능이 꺼져 있습니다.")
    # compare_digest: 비교에 걸린 시간으로 키를 추측하지 못하게 함
    # encode(): 한글 등 ASCII가 아닌 헤더 값이 와도 500 오류 없이 비교
    if not x_admin_key or not secrets.compare_digest(x_admin_key.encode(), settings.ADMIN_API_KEY.encode()):
        logger.warning("[전체 로그 조회 거부] 관리자 키가 없거나 올바르지 않음")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="관리자 키가 올바르지 않습니다.")

@router.get("/admin", response_model=List[ChatLogResponse], dependencies=[Depends(verify_admin_key)])
def read_all_logs(
    skip: int = Query(0, ge=0, description="건너뛸 로그 수"),
    limit: int = Query(100, ge=1, le=500, description="가져올 로그 수 (최대 500)"),
    db: Session = Depends(get_db),
):
    """[관리자/평가자 확인용] 전체 사용자의 대화 로그를 최신순으로 페이지 단위 조회"""
    logs = get_all_chat_logs(skip=skip, limit=limit, db=db)
    logger.info(f"[전체 대화 로그 조회] skip={skip}, limit={limit}, 건수={len(logs)}")
    return logs
