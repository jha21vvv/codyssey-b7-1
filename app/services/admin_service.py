import math
from datetime import timedelta
from typing import Dict, Iterable, List, Optional
from sqlalchemy import case, func
from sqlalchemy.orm import Session
from app.core.timeutil import utc_now
from app.models.chat_log import ChatLog
from app.models.request_log import RequestLog
from app.models.user import ADMIN_ROLE, User
from app.schemas.admin import (
    AdminChatLogItem,
    AdminSummary,
    ChatLogPage,
    ChatStats,
    CodeCount,
    RequestLogItem,
    RequestLogPage,
    RequestStats,
    RequestTrace,
    UserStats,
)
from app.services.auth_service import hash_password
from app.services.log_service import count_all_chat_logs, get_all_chat_logs

"""
[권태현 전담] 관리자 API·관리자 계정 관리 서비스
요청 로그(request_logs), 대화 로그(chat_logs), 사용자(users)를 모아
서비스 상태 요약, 요청 로그·대화 로그 목록, 요청 ID 추적을 만들고 관리자 지정·해제를 처리합니다.
"""

SUMMARY_WINDOW_HOURS = 24  # 요약 통계 기간
RECENT_ERROR_COUNT = 10
TOP_ERROR_CODE_COUNT = 5
ADMIN_PATH_PREFIX = "/api/admin"  # 관리자 화면이 보내는 요청 (요청 로그 목록에서 숨길 수 있음)

# 요청 로그 상태 필터: 이름 -> (최소 상태 코드, 최대 상태 코드)
STATUS_RANGES = {
    "2xx": (200, 299),
    "4xx": (400, 499),
    "5xx": (500, 599),
    "errors": (400, 599),
}


def _usernames(db: Session, user_ids: Iterable[Optional[int]]) -> Dict[int, str]:
    """사용자 id 목록의 아이디를 한 번의 조회로 가져옴 (줄마다 조회하지 않게)"""
    ids = {user_id for user_id in user_ids if user_id is not None}
    if not ids:
        return {}
    return dict(db.query(User.id, User.username).filter(User.id.in_(ids)).all())


def _user_id_of(db: Session, username: str) -> Optional[int]:
    row = db.query(User.id).filter(User.username == username).first()
    return row[0] if row else None


def _request_item(log: RequestLog, usernames: Dict[int, str]) -> RequestLogItem:
    item = RequestLogItem.model_validate(log)
    item.username = usernames.get(log.user_id)
    return item


def _chat_item(log: ChatLog, usernames: Dict[int, str]) -> AdminChatLogItem:
    item = AdminChatLogItem.model_validate(log)
    item.username = usernames.get(log.user_id)
    return item


def _percent(part: int, whole: int) -> float:
    return round(part / whole * 100, 1) if whole else 0.0


def _rounded(value: Optional[float]) -> Optional[int]:
    return int(round(value)) if value is not None else None


# -------------------------------------------------------------
# 1. 요청 로그 목록
# -------------------------------------------------------------
def list_request_logs(
    db: Session,
    skip: int,
    limit: int,
    status: str = "all",
    path: Optional[str] = None,
    username: Optional[str] = None,
    min_duration_ms: Optional[int] = None,
    exclude_admin: bool = False,
    error_code: Optional[str] = None,
    since_hours: Optional[int] = None,
) -> RequestLogPage:
    """조건에 맞는 요청 로그를 최신순으로 페이지 단위 조회"""
    query = db.query(RequestLog)
    if since_hours is not None:
        query = query.filter(RequestLog.created_at >= utc_now() - timedelta(hours=since_hours))
    if status in STATUS_RANGES:
        low, high = STATUS_RANGES[status]
        query = query.filter(RequestLog.status_code.between(low, high))
    if path:
        # autoescape: 검색어의 % _ 를 글자 그대로 찾음
        query = query.filter(RequestLog.path.contains(path, autoescape=True))
    if username:
        user_id = _user_id_of(db, username)
        if user_id is None:
            return RequestLogPage(total=0, skip=skip, limit=limit, items=[])
        query = query.filter(RequestLog.user_id == user_id)
    if min_duration_ms is not None:
        query = query.filter(RequestLog.duration_ms >= min_duration_ms)
    if error_code:
        query = query.filter(RequestLog.error_code == error_code)
    if exclude_admin:
        query = query.filter(~RequestLog.path.startswith(ADMIN_PATH_PREFIX))

    total = query.count()
    logs = query.order_by(RequestLog.created_at.desc(), RequestLog.id.desc()).offset(skip).limit(limit).all()
    usernames = _usernames(db, (log.user_id for log in logs))
    return RequestLogPage(total=total, skip=skip, limit=limit, items=[_request_item(log, usernames) for log in logs])


# -------------------------------------------------------------
# 2. 대화 로그 목록
# -------------------------------------------------------------
def list_chat_logs(
    db: Session,
    skip: int,
    limit: int,
    status: Optional[str] = None,
    username: Optional[str] = None,
) -> ChatLogPage:
    """전체 사용자의 대화 로그를 최신순으로 조회 (상태·사용자 조건 선택)"""
    user_id = None
    if username:
        user_id = _user_id_of(db, username)
        if user_id is None:
            return ChatLogPage(total=0, skip=skip, limit=limit, items=[])
    logs = get_all_chat_logs(skip=skip, limit=limit, db=db, status=status, user_id=user_id)
    total = count_all_chat_logs(db=db, status=status, user_id=user_id)
    usernames = _usernames(db, (log.user_id for log in logs))
    return ChatLogPage(total=total, skip=skip, limit=limit, items=[_chat_item(log, usernames) for log in logs])


# -------------------------------------------------------------
# 3. 요청 ID 추적
# -------------------------------------------------------------
def get_request_trace(db: Session, request_id: str) -> Optional[RequestTrace]:
    """
    요청 ID 하나로 요청 로그와 대화 로그를 함께 찾음 (둘 다 없으면 None)
    요청 로그 저장에 실패한 경우에도 대화 로그만으로 추적할 수 있게 따로 찾음
    """
    log = (
        db.query(RequestLog)
        .filter(RequestLog.request_id == request_id)
        .order_by(RequestLog.id.desc())
        .first()
    )
    chat = (
        db.query(ChatLog)
        .filter(ChatLog.request_id == request_id)
        .order_by(ChatLog.id.desc())
        .first()
    )
    if log is None and chat is None:
        return None
    usernames = _usernames(db, [log.user_id if log else None, chat.user_id if chat else None])
    return RequestTrace(
        request_id=request_id,
        request=_request_item(log, usernames) if log else None,
        chat_log=_chat_item(chat, usernames) if chat else None,
    )


# -------------------------------------------------------------
# 4. 서비스 상태 요약
# -------------------------------------------------------------
def _p95_duration(db: Session, since, total: int) -> Optional[int]:
    """요청 시간의 95번째 백분위수: 짧은 순으로 줄 세웠을 때 95% 위치의 값 (SQLite에 백분위 함수가 없어 직접 계산)"""
    if not total:
        return None
    position = math.ceil(total * 0.95) - 1
    return (
        db.query(RequestLog.duration_ms)
        .filter(RequestLog.created_at >= since)
        .order_by(RequestLog.duration_ms.asc())
        .offset(position)
        .limit(1)
        .scalar()
    )


def get_summary(db: Session) -> AdminSummary:
    now = utc_now()
    since = now - timedelta(hours=SUMMARY_WINDOW_HOURS)

    users = UserStats(
        total=db.query(func.count(User.id)).scalar() or 0,
        admins=db.query(func.count(User.id)).filter(User.role == ADMIN_ROLE).scalar() or 0,
        new_24h=db.query(func.count(User.id)).filter(User.created_at >= since).scalar() or 0,
    )

    # 대화: 전체 기간 성공/실패, 최근 24시간, 실패 종류별 건수
    by_status = dict(db.query(ChatLog.status, func.count(ChatLog.id)).group_by(ChatLog.status).all())
    recent_by_status = dict(
        db.query(ChatLog.status, func.count(ChatLog.id))
        .filter(ChatLog.created_at >= since)
        .group_by(ChatLog.status)
        .all()
    )
    avg_latency = (
        db.query(func.avg(ChatLog.latency_ms))
        .filter(ChatLog.created_at >= since, ChatLog.status == "SUCCESS", ChatLog.latency_ms.isnot(None))
        .scalar()
    )
    failure_rows = (
        db.query(ChatLog.error_type, func.count(ChatLog.id))
        .filter(ChatLog.status == "FAILED")
        .group_by(ChatLog.error_type)
        .order_by(func.count(ChatLog.id).desc())
        .all()
    )
    chat_total = sum(by_status.values())
    chats = ChatStats(
        total=chat_total,
        success=by_status.get("SUCCESS", 0),
        failed=by_status.get("FAILED", 0),
        failure_rate=_percent(by_status.get("FAILED", 0), chat_total),
        last_24h=sum(recent_by_status.values()),
        failed_24h=recent_by_status.get("FAILED", 0),
        avg_latency_ms_24h=_rounded(avg_latency),
        # 실패 종류를 기록하기 전(이전 버전)에 쌓인 실패는 UNKNOWN으로 묶음
        failures_by_type=[CodeCount(code=error_type or "UNKNOWN", count=count) for error_type, count in failure_rows],
    )

    # 요청: 최근 24시간 상태 코드 묶음별 건수, 평균·p95 응답 시간, 많이 난 오류 코드
    total, ok, client_errors, server_errors, avg_duration = (
        db.query(
            func.count(RequestLog.id),
            func.sum(case((RequestLog.status_code.between(200, 299), 1), else_=0)),
            func.sum(case((RequestLog.status_code.between(400, 499), 1), else_=0)),
            func.sum(case((RequestLog.status_code >= 500, 1), else_=0)),
            func.avg(RequestLog.duration_ms),
        )
        .filter(RequestLog.created_at >= since)
        .one()
    )
    error_code_rows = (
        db.query(RequestLog.error_code, func.count(RequestLog.id))
        .filter(RequestLog.created_at >= since, RequestLog.error_code.isnot(None))
        .group_by(RequestLog.error_code)
        .order_by(func.count(RequestLog.id).desc(), RequestLog.error_code)
        .limit(TOP_ERROR_CODE_COUNT)
        .all()
    )
    requests = RequestStats(
        window_hours=SUMMARY_WINDOW_HOURS,
        total=total or 0,
        status_2xx=ok or 0,
        status_4xx=client_errors or 0,
        status_5xx=server_errors or 0,
        server_error_rate=_percent(server_errors or 0, total or 0),
        avg_duration_ms=_rounded(avg_duration),
        p95_duration_ms=_p95_duration(db, since, total or 0),
        top_error_codes=[CodeCount(code=code, count=count) for code, count in error_code_rows],
    )

    error_logs = (
        db.query(RequestLog)
        .filter(RequestLog.status_code >= 400)
        .order_by(RequestLog.created_at.desc(), RequestLog.id.desc())
        .limit(RECENT_ERROR_COUNT)
        .all()
    )
    usernames = _usernames(db, (log.user_id for log in error_logs))
    return AdminSummary(
        generated_at=now,
        users=users,
        chats=chats,
        requests=requests,
        recent_errors=[_request_item(log, usernames) for log in error_logs],
    )


# -------------------------------------------------------------
# 5. 관리자 지정·해제 (scripts/create_admin.py에서 사용)
# -------------------------------------------------------------
def set_user_role(db: Session, username: str, role: str) -> Optional[User]:
    """가입한 사용자의 역할을 바꿈 (사용자가 없으면 None)"""
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        return None
    user.role = role
    db.commit()
    db.refresh(user)
    return user


def create_user_with_role(db: Session, username: str, password: str, role: str) -> User:
    """역할을 정해 새 사용자를 만듦 (비밀번호는 회원가입과 같은 bcrypt 해시로 저장)"""
    user = User(username=username, hashed_password=hash_password(password), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def list_admins(db: Session) -> List[User]:
    return db.query(User).filter(User.role == ADMIN_ROLE).order_by(User.id).all()
