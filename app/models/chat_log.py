from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from app.core.database import Base
from app.core.timeutil import utc_now

"""
[권태현 전담] 대화 로그(ChatLog) 테이블 모델
과제 필수 추적 필드(사용자 식별, 생성 시각, 질문, 응답)와 AI 응답 상태를 저장합니다.
user_id는 신재은의 User 모델(users 테이블)을 참조합니다.
"""

class ChatLog(Base):
    __tablename__ = "chat_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    prompt = Column(Text, nullable=False)
    response = Column(Text, nullable=False)
    # [안내서 대비 변경] 업무분장안내서 규칙 6(필수 5개 필드)에 맞춰 status도 NULL을 허용하지 않음
    status = Column(String(20), default="SUCCESS", nullable=False)  # "SUCCESS" 또는 "FAILED"
    # [안내서 대비 변경] 안내서의 default=datetime.utcnow는 Python 3.12부터 deprecated라 utc_now로 대체 (값은 같음)
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)  # UTC 기준
    # [권태현] 운영 추적용 (이전 버전 DB에는 app/core/migrations.py가 컬럼을 추가)
    request_id = Column(String(16), nullable=True, index=True)  # 요청 로그·서버 로그와 같은 요청 ID
    latency_ms = Column(Integer, nullable=True)  # AI 응답까지 걸린 시간
    error_type = Column(String(30), nullable=True)  # 실패 종류 (TIMEOUT, UPSTREAM_ERROR, BAD_RESPONSE 등)
