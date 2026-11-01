from typing import Literal, Optional
from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session
from app.api.deps import get_current_admin
from app.core.database import get_db
from app.core.errors import ApiError, ErrorResponse
from app.core.logger import logger
from app.models.user import User
from app.schemas.admin import AdminSummary, ChatLogPage, RequestLogPage, RequestTrace
from app.services import admin_service

"""
[권태현 전담] 관리자 API (main.py에서 prefix="/api/admin"으로 연결)
모든 경로는 관리자 계정(role=admin)으로 로그인해야 쓸 수 있습니다.
- 토큰이 없거나 잘못됨: 401 AUTH_REQUIRED / 일반 사용자: 403 ADMIN_REQUIRED
- GET /api/admin/summary               : 서비스 상태 요약 (사용자·대화·최근 24시간 요청 통계, 최근 오류)
- GET /api/admin/requests              : 요청 로그 목록 (기간·상태 코드·주소·사용자·오류 코드·느린 요청 필터)
- GET /api/admin/requests/{request_id} : 요청 ID 하나로 요청 로그와 대화 로그를 함께 추적
- GET /api/admin/chat-logs             : 전체 사용자의 대화 로그 목록 (실패만 보기·사용자 필터)
"""

ADMIN_ERROR_DOCS = {
    401: {"model": ErrorResponse, "description": "로그인 필요 (AUTH_REQUIRED)"},
    403: {"model": ErrorResponse, "description": "관리자 계정이 아님 (ADMIN_REQUIRED)"},
}

# 라우터 전체에 관리자 검사를 걸어, 나중에 경로를 추가해도 검사가 빠지지 않게 함
# (경로 함수의 admin 인자는 같은 요청 안에서 검사 결과를 다시 쓰므로 두 번 조회하지 않음)
router = APIRouter(dependencies=[Depends(get_current_admin)], responses=ADMIN_ERROR_DOCS)


@router.get("/summary", response_model=AdminSummary)
def read_summary(admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    """서비스 상태 요약: 사용자 수, 대화 성공·실패와 실패 종류, 최근 24시간 요청 통계, 최근 오류"""
    summary = admin_service.get_summary(db)
    logger.info(f"[관리자 조회] 서비스 상태 요약 admin_id={admin.id}")
    return summary


@router.get("/requests", response_model=RequestLogPage)
def read_request_logs(
    skip: int = Query(0, ge=0, description="건너뛸 로그 수"),
    limit: int = Query(50, ge=1, le=200, description="가져올 로그 수 (최대 200)"),
    status: Literal["all", "2xx", "4xx", "5xx", "errors"] = Query("all", description="상태 코드 묶음 (errors = 4xx와 5xx)"),
    path: Optional[str] = Query(None, max_length=255, description="주소에 이 글자가 들어간 요청만 (예: /api/chat)"),
    username: Optional[str] = Query(None, max_length=50, description="이 사용자가 보낸 요청만"),
    min_duration_ms: Optional[int] = Query(None, ge=0, description="응답 시간이 이 값(ms) 이상인 느린 요청만"),
    exclude_admin: bool = Query(False, description="관리자 화면이 보낸 요청(/api/admin) 빼고 보기"),
    error_code: Optional[str] = Query(None, max_length=50, description="이 오류 코드가 난 요청만 (예: AI_TIMEOUT)"),
    since_hours: Optional[int] = Query(None, ge=1, le=24 * 90, description="최근 몇 시간 동안의 요청만 (예: 24)"),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """요청 로그 목록 (최신순)"""
    page = admin_service.list_request_logs(
        db,
        skip=skip,
        limit=limit,
        status=status,
        path=path,
        username=username,
        min_duration_ms=min_duration_ms,
        exclude_admin=exclude_admin,
        error_code=error_code,
        since_hours=since_hours,
    )
    logger.info(f"[관리자 조회] 요청 로그 admin_id={admin.id}, status={status}, 건수={len(page.items)}/{page.total}")
    return page


@router.get(
    "/requests/{request_id}",
    response_model=RequestTrace,
    responses={404: {"model": ErrorResponse, "description": "해당 요청 ID의 기록 없음 (REQUEST_NOT_FOUND)"}},
)
def read_request_trace(
    # 요청 ID는 영문·숫자·하이픈만 받음 (서버 로그에 이상한 글자가 남지 않게)
    request_id: str = Path(..., min_length=1, max_length=16, pattern=r"^[0-9A-Za-z-]+$", description="응답 헤더 X-Request-ID 값"),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """요청 ID 하나로 요청 로그(상태 코드·응답 시간·오류 코드)와 대화 로그(질문·응답·실패 종류)를 함께 조회"""
    trace = admin_service.get_request_trace(db, request_id)
    if trace is None:
        raise ApiError(404, "REQUEST_NOT_FOUND", "해당 요청 ID의 기록이 없습니다.")
    logger.info(f"[관리자 조회] 요청 추적 admin_id={admin.id}, request_id={request_id}")
    return trace


@router.get("/chat-logs", response_model=ChatLogPage)
def read_chat_logs(
    skip: int = Query(0, ge=0, description="건너뛸 로그 수"),
    limit: int = Query(50, ge=1, le=200, description="가져올 로그 수 (최대 200)"),
    status: Literal["all", "SUCCESS", "FAILED"] = Query("all", description="FAILED로 실패한 대화만 보기"),
    username: Optional[str] = Query(None, max_length=50, description="이 사용자의 대화만"),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """전체 사용자의 대화 로그 목록 (최신순, 사용자 아이디·요청 ID·AI 응답 시간·실패 종류 포함)"""
    page = admin_service.list_chat_logs(
        db,
        skip=skip,
        limit=limit,
        status=None if status == "all" else status,
        username=username,
    )
    logger.info(f"[관리자 조회] 대화 로그 admin_id={admin.id}, status={status}, 건수={len(page.items)}/{page.total}")
    return page
