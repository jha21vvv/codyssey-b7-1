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
