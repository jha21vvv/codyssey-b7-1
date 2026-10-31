from typing import Optional
from pydantic import BaseModel, Field

"""
[조명환 전담] AI 챗봇 요청(ChatRequest) 및 응답(ChatResponse) DTO 스키마
프론트엔드(권태현)의 POST /api/chat 비동기 Fetch 통신 규격과 일치합니다.
"""


class ChatRequest(BaseModel):
    prompt: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="사용자 질문 (빈 문자열 차단, 최대 1000자)",
    )


class ChatResponse(BaseModel):
    prompt: str = Field(..., description="검증된 사용자 질문")
    response: str = Field(..., description="AI 응답 또는 장애 시 Fallback 안내 메시지")
    status: str = Field(default="SUCCESS", description="SUCCESS 또는 FAILED")
    context_used_count: int = Field(default=0, description="컨텍스트에 반영된 직전 대화 수")


class ChatFailureResponse(BaseModel):
    """[권태현] AI 장애(502·503·504) 응답: 공통 오류 형식에 대화 정보를 더함 (화면은 response를 실패 말풍선으로 표시)"""
    detail: str = Field(..., description="사용자에게 보여줄 안내 문구")
    code: str = Field(..., description="AI_TIMEOUT, AI_UPSTREAM_ERROR, AI_CONNECTION_ERROR, AI_NOT_CONFIGURED")
    request_id: Optional[str] = Field(None, description="요청 ID (서버 로그·요청 로그·대화 로그와 같은 값)")
    prompt: str
    response: str
    status: str = Field(default="FAILED")
    context_used_count: int = 0
