from sqlalchemy import Column, Integer, String, DateTime
from app.core.database import Base
from app.core.timeutil import utc_now

"""
[권태현 전담] 요청 로그(RequestLog) 테이블 모델
모든 API 요청(/api/...)을 한 줄씩 남겨 상태 코드, 응답 시간, 사용자, 오류 코드로 운영 상황을 추적합니다.
request_id는 응답 헤더(X-Request-ID), 오류 응답 본문, 서버 로그, 대화 로그(chat_logs.request_id)에 같은 값으로 남습니다.
"""

class RequestLog(Base):
    __tablename__ = "request_logs"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(String(16), nullable=False, index=True)
    method = Column(String(10), nullable=False)
    path = Column(String(255), nullable=False, index=True)
    status_code = Column(Integer, nullable=False, index=True)
    duration_ms = Column(Integer, nullable=False)  # 요청을 받고 응답할 때까지 걸린 시간
    # 로그인한 요청만 채워짐. 사용자가 지워져도 요청 기록은 남아야 해서 외래키는 걸지 않음
    user_id = Column(Integer, nullable=True, index=True)
    client_ip = Column(String(64), nullable=True)
    user_agent = Column(String(255), nullable=True)
    error_code = Column(String(50), nullable=True)  # 오류 응답의 code (예: AUTH_REQUIRED, AI_TIMEOUT)
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)  # UTC 기준
