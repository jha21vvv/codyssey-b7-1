from datetime import datetime
from pydantic import BaseModel, ConfigDict

"""
[권태현 전담] 대화 로그 응답 스키마
ChatLog ORM 객체를 그대로 받아 로그 조회 API의 JSON 응답으로 변환합니다.
"""

class ChatLogResponse(BaseModel):
    # [안내서 대비 변경] 안내서의 class Config 방식은 Pydantic v2에서 deprecated라 model_config(ConfigDict)로 지정
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    prompt: str
    response: str
    status: str
    created_at: datetime
