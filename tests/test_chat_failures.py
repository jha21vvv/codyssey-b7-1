import asyncio
import io
import logging
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.main import app
from app.core.config import settings
from app.core.database import Base, get_db
from app.core.logger import logger
from app.models.chat_log import ChatLog
from app.services.ai_service import AIResult, FALLBACK_ERROR_MESSAGE, FALLBACK_TIMEOUT_MESSAGE, call_ai_api
from app.services.log_service import save_chat_log

"""
[권태현 전담] AI 장애 처리(원인별 상태 코드, 실패 종류 기록, 내부 정보 미노출)와 대화 로그 추적 정보 검증 테스트
"""

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    yield
    if previous_override is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = previous_override
    Base.metadata.drop_all(bind=engine)

def login_headers(username: str = "alice1"):
    client.post("/api/auth/register", json={"username": username, "password": "password123"})
    token = client.post("/api/auth/login", json={"username": username, "password": "password123"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}

def fake_http_client(response=None, error=None):
    """httpx.AsyncClient를 가짜로 바꿔 AI 서버 응답이나 통신 오류를 흉내 냄"""
    instance = AsyncMock()
    if error is not None:
        instance.post.side_effect = error
    else:
        instance.post.return_value = response
    context = MagicMock()
    context.__aenter__.return_value = instance
    context.__aexit__.return_value = None
    return patch("app.services.ai_service.httpx.AsyncClient", return_value=context)

def ok_response(payload):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = payload
    return response

def chat_logs():
    db = TestingSessionLocal()
    try:
        return db.query(ChatLog).order_by(ChatLog.id).all()
    finally:
        db.close()

# -------------------------------------------------------------
# 1. AI 호출 결과의 실패 종류
# -------------------------------------------------------------
@pytest.mark.parametrize("payload", [
    {"choices": [{"message": {"content": None}}]},   # 안전 필터 등으로 답변이 null
    {"choices": [{"message": {"content": "   "}}]},  # 빈 답변
    {"error": "unexpected"},                          # 형식이 다른 응답
])
def test_empty_or_unexpected_ai_reply_is_bad_response(monkeypatch, payload):
    monkeypatch.setattr(settings, "AI_API_KEY", "sk-test-valid-key")
    with fake_http_client(ok_response(payload)):
        result = asyncio.run(call_ai_api([{"role": "user", "content": "질문"}]))
    assert result == AIResult(FALLBACK_ERROR_MESSAGE, "FAILED", "BAD_RESPONSE")

def test_connection_error_returns_guide_message_only(monkeypatch):
    monkeypatch.setattr(settings, "AI_API_KEY", "sk-test-valid-key")
    with fake_http_client(error=httpx.ConnectError("[Errno -3] Temporary failure in name resolution")):
        result = asyncio.run(call_ai_api([{"role": "user", "content": "질문"}]))
    assert result == AIResult(FALLBACK_ERROR_MESSAGE, "FAILED", "CONNECTION_ERROR")

# -------------------------------------------------------------
# 2. 채팅 API의 원인별 상태 코드
# -------------------------------------------------------------
@pytest.mark.parametrize("error_type, message, status_code, code", [
    ("TIMEOUT", FALLBACK_TIMEOUT_MESSAGE, 504, "AI_TIMEOUT"),
    ("UPSTREAM_ERROR", FALLBACK_ERROR_MESSAGE, 502, "AI_UPSTREAM_ERROR"),
    ("BAD_RESPONSE", FALLBACK_ERROR_MESSAGE, 502, "AI_BAD_RESPONSE"),
    ("CONNECTION_ERROR", FALLBACK_ERROR_MESSAGE, 502, "AI_CONNECTION_ERROR"),
    ("NOT_CONFIGURED", FALLBACK_ERROR_MESSAGE, 503, "AI_NOT_CONFIGURED"),
])
def test_ai_failure_status_codes(error_type, message, status_code, code):
    headers = login_headers()
    with patch("app.api.chat_router.call_ai_api", new=AsyncMock(return_value=AIResult(message, "FAILED", error_type))):
        response = client.post("/api/chat", json={"prompt": "질문"}, headers=headers)

    assert response.status_code == status_code
    body = response.json()
    assert (body["code"], body["status"], body["detail"], body["response"]) == (code, "FAILED", message, message)
    assert body["request_id"] == response.headers["X-Request-ID"]
    # 실패해도 대화는 FAILED와 실패 종류로 저장
    log = chat_logs()[-1]
    assert (log.status, log.error_type) == ("FAILED", error_type)

def test_empty_ai_reply_returns_502_instead_of_500(monkeypatch):
    """예전에는 AI 답변이 null이면 DB 저장과 응답 검증이 실패해 500이 났음"""
    monkeypatch.setattr(settings, "AI_API_KEY", "sk-test-valid-key")
    headers = login_headers()
    with fake_http_client(ok_response({"choices": [{"message": {"content": None}}]})):
        response = client.post("/api/chat", json={"prompt": "질문"}, headers=headers)
    assert response.status_code == 502
    assert response.json()["code"] == "AI_BAD_RESPONSE"
    assert chat_logs()[-1].error_type == "BAD_RESPONSE"

def test_connection_error_text_not_shown_to_user(monkeypatch):
    """예전에는 영어 예외 문구가 그대로 화면과 DB에 남았음"""
    monkeypatch.setattr(settings, "AI_API_KEY", "sk-test-valid-key")
    headers = login_headers()
    with fake_http_client(error=httpx.ConnectError("[Errno -3] secret-host")):
        response = client.post("/api/chat", json={"prompt": "질문"}, headers=headers)
    assert response.status_code == 502
    assert "Errno" not in response.text and "secret-host" not in response.text
    assert chat_logs()[-1].response == FALLBACK_ERROR_MESSAGE

# -------------------------------------------------------------
# 3. 대화 로그 추적 정보
# -------------------------------------------------------------
def test_chat_log_saves_request_id_and_latency():
    headers = login_headers()
    with patch("app.api.chat_router.call_ai_api", new=AsyncMock(return_value=AIResult("답변", "SUCCESS"))):
        response = client.post("/api/chat", json={"prompt": "질문"}, headers=headers)
    assert response.status_code == 200
    log = chat_logs()[-1]
    assert log.request_id == response.headers["X-Request-ID"]
    assert log.latency_ms is not None and log.latency_ms >= 0
    assert log.error_type is None

def test_context_used_count_counts_only_success_logs():
    """직전 대화가 모두 실패면 AI에 들어간 이전 대화는 0개"""
    headers = login_headers()
    user_id = client.get("/api/auth/me", headers=headers).json()["id"]
    db = TestingSessionLocal()
    for i in range(3):
        save_chat_log(user_id=user_id, prompt=f"실패 질문 {i}", response=FALLBACK_TIMEOUT_MESSAGE, status="FAILED", db=db)
    db.close()

    with patch("app.api.chat_router.call_ai_api", new=AsyncMock(return_value=AIResult("답변", "SUCCESS"))):
        response = client.post("/api/chat", json={"prompt": "새 질문"}, headers=headers)
    assert response.json()["context_used_count"] == 0

def test_db_failure_log_does_not_contain_prompt():
    """DB 오류 문자열에는 질문 내용이 든 SQL 파라미터가 섞여 있어 서버 로그에는 원인만 남겨야 함"""
    headers = login_headers()
    secret_prompt = "개인정보가 들어간 질문"
    db_error = IntegrityError("INSERT INTO chat_logs ...", (1, secret_prompt), Exception("NOT NULL constraint failed: chat_logs.response"))
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)
    try:
        with patch("app.api.chat_router.call_ai_api", new=AsyncMock(return_value=AIResult("답변", "SUCCESS"))), \
                patch("app.api.chat_router.save_chat_log", side_effect=db_error):
            response = client.post("/api/chat", json={"prompt": secret_prompt}, headers=headers)
    finally:
        logger.removeHandler(handler)

    assert response.status_code == 200
    logs = stream.getvalue()
    assert "[DB 저장 실패]" in logs and "NOT NULL constraint failed" in logs
    assert secret_prompt not in logs
