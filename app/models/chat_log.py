from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from app.core.database import Base

"""
[권태현 전담] 대화 로그(ChatLog) 테이블 모델
과제 필수 추적 필드(사용자 식별, 생성 시각, 질문, 응답)와 AI 응답 상태를 저장합니다.
user_id는 신재은의 User 모델(users 테이블)을 참조합니다.
"""

def _utc_now() -> datetime:
    # [안내서 대비 변경] 안내서의 default=datetime.utcnow는 Python 3.12부터 deprecated라,
    # 같은 값(timezone 정보 없는 UTC 시각)을 만드는 함수로 대체
    return datetime.now(timezone.utc).replace(tzinfo=None)

class ChatLog(Base):
    __tablename__ = "chat_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    prompt = Column(Text, nullable=False)
    response = Column(Text, nullable=False)
    # [안내서 대비 변경] 업무분장안내서 규칙 6(필수 5개 필드)에 맞춰 status도 NULL을 허용하지 않음
    status = Column(String(20), default="SUCCESS", nullable=False)  # "SUCCESS" 또는 "FAILED"
    created_at = Column(DateTime, default=_utc_now, nullable=False, index=True)  # UTC 기준
