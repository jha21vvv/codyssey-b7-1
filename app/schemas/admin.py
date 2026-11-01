from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict

"""
[권태현 전담] 관리자 API 응답 스키마
시각은 다른 API와 같이 timezone 정보 없는 UTC로 보내고, 관리자 화면이 한국 시간으로 바꿔 보여줍니다.
"""


class RequestLogItem(BaseModel):
    """요청 로그(request_logs) 한 줄 + 요청을 보낸 사용자 아이디"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    request_id: str
    method: str
    path: str
    status_code: int
    duration_ms: int
    user_id: Optional[int] = None
    username: Optional[str] = None  # 로그인하지 않은 요청이거나 사용자가 지워졌으면 null
    client_ip: Optional[str] = None
    user_agent: Optional[str] = None
    error_code: Optional[str] = None
    created_at: datetime


class RequestLogPage(BaseModel):
    total: int  # 조건에 맞는 전체 건수 (페이지 이동용)
    skip: int
    limit: int
    items: List[RequestLogItem]


class AdminChatLogItem(BaseModel):
    """대화 로그(chat_logs) 한 줄 + 사용자 아이디와 추적 정보"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    username: Optional[str] = None
    prompt: str
    response: str
    status: str
    created_at: datetime
    request_id: Optional[str] = None
    latency_ms: Optional[int] = None
    error_type: Optional[str] = None


class ChatLogPage(BaseModel):
    total: int
    skip: int
    limit: int
    items: List[AdminChatLogItem]


class RequestTrace(BaseModel):
    """요청 ID 하나에 남은 기록 (요청 로그, 그 요청에서 저장된 대화 로그)"""
    request_id: str
    request: Optional[RequestLogItem] = None
    chat_log: Optional[AdminChatLogItem] = None


class CodeCount(BaseModel):
    code: str
    count: int


class UserStats(BaseModel):
    total: int
    admins: int
    new_24h: int


class ChatStats(BaseModel):
    total: int
    success: int
    failed: int
    failure_rate: float  # 전체 대화 중 실패 비율 (%)
    last_24h: int
    failed_24h: int
    avg_latency_ms_24h: Optional[int] = None  # 최근 24시간 동안 성공한 대화의 평균 AI 응답 시간
    failures_by_type: List[CodeCount]  # 실패 종류별 건수 (TIMEOUT, UPSTREAM_ERROR 등)


class RequestStats(BaseModel):
    window_hours: int  # 통계 기간 (최근 몇 시간)
    total: int
    status_2xx: int
    status_4xx: int
    status_5xx: int
    server_error_rate: float  # 5xx 비율 (%)
    avg_duration_ms: Optional[int] = None
    p95_duration_ms: Optional[int] = None  # 요청 95%가 이 시간 안에 끝남
    top_error_codes: List[CodeCount]


class AdminSummary(BaseModel):
    generated_at: datetime
    users: UserStats
    chats: ChatStats
    requests: RequestStats
    recent_errors: List[RequestLogItem]  # 상태 코드 400 이상인 최근 요청
