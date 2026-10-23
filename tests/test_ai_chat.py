import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.core.config import settings
from app.core.database import Base, get_db
from app.main import app
from app.models.chat_log import ChatLog
from app.models.user import User
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.ai_service import (
    DEFAULT_GEMINI_MODEL,
    FALLBACK_ERROR_MESSAGE,
    FALLBACK_TIMEOUT_MESSAGE,
    GEMINI_API_URL,
    SYSTEM_PROMPT,
    build_chat_context,
    call_ai_api,
    validate_prompt,
)

"""
[조명환 전담] AI 파이프라인(입력 검증, 컨텍스트 조립, 비동기 AI 호출, 타임아웃 방어 및 POST /api/chat 통합) 테스트
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
def setup_test_db():
    Base.metadata.create_all(bind=engine)
    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    yield
    if previous_override is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = previous_override
    Base.metadata.drop_all(bind=engine)


def get_auth_headers(username: str = "chatuser1") -> dict:
    """테스트용 회원가입 및 로그인 후 Bearer 토큰 헤더 반환"""
    client.post("/api/auth/register", json={"username": username, "password": "password123"})
    res = client.post("/api/auth/login", json={"username": username, "password": "password123"})
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# -------------------------------------------------------------
# 1. 스키마, 입력 검증, 컨텍스트 빌더 및 AI 클라이언트 단위 테스트
# -------------------------------------------------------------
def test_chat_schemas_valid():
    """ChatRequest 및 ChatResponse 스키마 정상 생성 검증"""
    req = ChatRequest(prompt="안녕하세요")
    assert req.prompt == "안녕하세요"

    res = ChatResponse(prompt="안녕하세요", response="반갑습니다!", status="SUCCESS", context_used_count=2)
    assert res.status == "SUCCESS"
    assert res.context_used_count == 2


def test_chat_request_empty_blocked():
    """ChatRequest에 빈 문자열 전달 시 Pydantic ValidationError 발생 검증"""
    with pytest.raises(ValidationError):
        ChatRequest(prompt="")


def test_validate_prompt_success_and_strip():
    """앞뒤 공백 제거 후 정상 문자열 반환 검증"""
    assert validate_prompt("  파이썬 FastAPI 질문입니다.  ") == "파이썬 FastAPI 질문입니다."


def test_validate_prompt_whitespace_only_blocked():
    """공백이나 줄바꿈만 있는 질문 차단 검증 (과제 요구사항 72-73)"""
    with pytest.raises(ValueError, match="비어 있습니다"):
        validate_prompt("     \n\t  ")


def test_validate_prompt_max_length_exceeded():
    """1,000자 초과 질문 차단 검증 (과제 요구사항 72-73)"""
    long_prompt = "가" * 1001
    with pytest.raises(ValueError, match="최대 1000자"):
        validate_prompt(long_prompt)


def test_build_chat_context_chronological_and_filter_failed():
    """
    최근 N개 대화 이력(최신순 조회 결과)을 시간순(역순)으로 조립하고,
    FAILED 상태 로그는 컨텍스트에서 제외하는지 검증 (과제 요구사항 60-61)
    """
    # get_user_chat_logs는 최신순(DESC)으로 반환하므로 [가장 최근, 중간, 가장 오래된] 순서
    recent_logs = [
        SimpleNamespace(prompt="세 번째 질문(실패)", response="타임아웃 안내", status="FAILED"),
        SimpleNamespace(prompt="두 번째 질문", response="두 번째 답변", status="SUCCESS"),
        SimpleNamespace(prompt="첫 번째 질문", response="첫 번째 답변", status="SUCCESS"),
    ]

    messages = build_chat_context(recent_logs=recent_logs, current_prompt="네 번째 현재 질문")

    assert messages[0] == {"role": "system", "content": SYSTEM_PROMPT}
    # 오래된 대화가 먼저 배치되어야 함
    assert messages[1] == {"role": "user", "content": "첫 번째 질문"}
    assert messages[2] == {"role": "assistant", "content": "첫 번째 답변"}
    assert messages[3] == {"role": "user", "content": "두 번째 질문"}
    assert messages[4] == {"role": "assistant", "content": "두 번째 답변"}
    # FAILED 로그는 제외되고 마지막에 현재 질문이 위치해야 함
    assert messages[5] == {"role": "user", "content": "네 번째 현재 질문"}
    assert len(messages) == 6


def test_call_ai_api_success(monkeypatch):
    """AI API 정상 응답(200 OK) 시 답변 텍스트와 SUCCESS 반환 검증"""
    monkeypatch.setattr(settings, "AI_API_KEY", "sk-test-valid-key")
    monkeypatch.setattr(settings, "AI_BASE_URL", "")
    monkeypatch.setattr(settings, "AI_MODEL_NAME", "gpt-4o-mini")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "안녕하세요! 무엇을 도와드릴까요?"}}]
    }

    mock_client_instance = AsyncMock()
    mock_client_instance.post.return_value = mock_response
    mock_client_ctx = MagicMock()
    mock_client_ctx.__aenter__.return_value = mock_client_instance
    mock_client_ctx.__aexit__.return_value = None

    with patch("app.services.ai_service.httpx.AsyncClient", return_value=mock_client_ctx):
        reply, status = asyncio.run(call_ai_api([{"role": "user", "content": "안녕"}]))

    assert status == "SUCCESS"
    assert reply == "안녕하세요! 무엇을 도와드릴까요?"


def test_call_ai_api_gemini_key_auto_routing(monkeypatch):
    """Gemini API 키(AIza...) 설정 시 자동으로 Gemini 호환 엔드포인트 및 기본 모델로 호출되는지 검증"""
    monkeypatch.setattr(settings, "AI_API_KEY", "AIzaSy-test-gemini-key")
    monkeypatch.setattr(settings, "AI_MODEL_NAME", "gpt-4o-mini")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "Gemini 응답입니다."}}]
    }

    mock_client_instance = AsyncMock()
    mock_client_instance.post.return_value = mock_response
    mock_client_ctx = MagicMock()
    mock_client_ctx.__aenter__.return_value = mock_client_instance
    mock_client_ctx.__aexit__.return_value = None

    with patch("app.services.ai_service.httpx.AsyncClient", return_value=mock_client_ctx):
        reply, status = asyncio.run(call_ai_api([{"role": "user", "content": "안녕"}]))

    assert status == "SUCCESS"
    assert reply == "Gemini 응답입니다."
    called_url = mock_client_instance.post.call_args.args[0]
    called_payload = mock_client_instance.post.call_args.kwargs["json"]
    assert called_url == GEMINI_API_URL
    assert called_payload["model"] == DEFAULT_GEMINI_MODEL


def test_call_ai_api_custom_base_url(monkeypatch):
    """AI_BASE_URL(코디세이 프록시 등) 설정 시 해당 엔드포인트로 정확히 호출되는지 검증"""
    monkeypatch.setattr(settings, "AI_API_KEY", "sk-cody-test-key")
    monkeypatch.setattr(settings, "AI_BASE_URL", "https://proxy.codyssey.kr/v1")
    monkeypatch.setattr(settings, "AI_MODEL_NAME", "gpt-4o-mini")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "코디세이 AI 응답입니다."}}]
    }

    mock_client_instance = AsyncMock()
    mock_client_instance.post.return_value = mock_response
    mock_client_ctx = MagicMock()
    mock_client_ctx.__aenter__.return_value = mock_client_instance
    mock_client_ctx.__aexit__.return_value = None

    with patch("app.services.ai_service.httpx.AsyncClient", return_value=mock_client_ctx):
        reply, status = asyncio.run(call_ai_api([{"role": "user", "content": "안녕"}]))

    assert status == "SUCCESS"
    assert reply == "코디세이 AI 응답입니다."
    called_url = mock_client_instance.post.call_args.args[0]
    assert called_url == "https://proxy.codyssey.kr/v1/chat/completions"


def test_call_ai_api_codyssey_key_auto_routing(monkeypatch):
    """sk-cody- 키 감지 시 자동으로 https://copa.codyssey.kr/v1/chat/completions 로 분기하는지 검증"""
    monkeypatch.setattr(settings, "AI_API_KEY", "sk-cody-live-test1234")
    monkeypatch.setattr(settings, "AI_BASE_URL", "")
    monkeypatch.setattr(settings, "AI_MODEL_NAME", "gpt-4o-mini")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "코디세이 자동 라우팅 응답"}}]
    }

    mock_client_instance = AsyncMock()
    mock_client_instance.post.return_value = mock_response
    mock_client_ctx = MagicMock()
    mock_client_ctx.__aenter__.return_value = mock_client_instance
    mock_client_ctx.__aexit__.return_value = None

    with patch("app.services.ai_service.httpx.AsyncClient", return_value=mock_client_ctx):
        reply, status = asyncio.run(call_ai_api([{"role": "user", "content": "안녕"}]))

    assert status == "SUCCESS"
    assert reply == "코디세이 자동 라우팅 응답"
    called_url = mock_client_instance.post.call_args.args[0]
    called_payload = mock_client_instance.post.call_args.kwargs["json"]
    assert called_url == "https://copa.codyssey.kr/v1/chat/completions"
    assert called_payload["model"] == "gpt-5-mini"


def test_call_ai_api_timeout_fallback(monkeypatch):
    """AI API 타임아웃(httpx.TimeoutException) 발생 시 서버 비정상 종료 없이 FAILED 및 안내 문구 반환 검증"""
    monkeypatch.setattr(settings, "AI_API_KEY", "sk-test-valid-key")

    mock_client_instance = AsyncMock()
    mock_client_instance.post.side_effect = httpx.TimeoutException("Request timed out")
    mock_client_ctx = MagicMock()
    mock_client_ctx.__aenter__.return_value = mock_client_instance
    mock_client_ctx.__aexit__.return_value = None

    with patch("app.services.ai_service.httpx.AsyncClient", return_value=mock_client_ctx):
        reply, status = asyncio.run(call_ai_api([{"role": "user", "content": "질문"}]))

    assert status == "FAILED"
    assert reply == FALLBACK_TIMEOUT_MESSAGE


def test_call_ai_api_http_error_fallback(monkeypatch):
    """AI API가 500 등 비정상 상태코드를 반환할 때 FAILED 및 Fallback 문구 반환 검증"""
    monkeypatch.setattr(settings, "AI_API_KEY", "sk-test-valid-key")

    mock_response = MagicMock()
    mock_response.status_code = 502
    mock_response.text = "Bad Gateway"

    mock_client_instance = AsyncMock()
    mock_client_instance.post.return_value = mock_response
    mock_client_ctx = MagicMock()
    mock_client_ctx.__aenter__.return_value = mock_client_instance
    mock_client_ctx.__aexit__.return_value = None

    with patch("app.services.ai_service.httpx.AsyncClient", return_value=mock_client_ctx):
        reply, status = asyncio.run(call_ai_api([{"role": "user", "content": "질문"}]))

    assert status == "FAILED"
    assert reply == FALLBACK_ERROR_MESSAGE


def test_call_ai_api_missing_key_fallback(monkeypatch):
    """AI_API_KEY 미설정 시 외부 네트워크 호출 없이 즉시 FAILED 및 안내 문구 반환 검증"""
    monkeypatch.setattr(settings, "AI_API_KEY", "")

    reply, status = asyncio.run(call_ai_api([{"role": "user", "content": "질문"}]))

    assert status == "FAILED"
    assert reply == FALLBACK_ERROR_MESSAGE


# -------------------------------------------------------------
# 2. POST /api/chat 엔드포인트 통합 테스트 (인증, DB 로그, 컨텍스트, 장애 격리)
# -------------------------------------------------------------
def test_chat_endpoint_unauthorized_blocked():
    """비로그인 사용자가 POST /api/chat 호출 시 401 Unauthorized로 차단되는지 검증 (규칙 3)"""
    res = client.post("/api/chat", json={"prompt": "비로그인 질문"})
    assert res.status_code == 401


def test_chat_endpoint_whitespace_prompt_blocked_422():
    """공백만 포함된 질문 전송 시 AI 호출 전 422 Unprocessable Entity로 차단되는지 검증 (규칙 5)"""
    headers = get_auth_headers("whitespaceuser")
    res = client.post("/api/chat", json={"prompt": "     "}, headers=headers)
    assert res.status_code == 422
    assert "비어 있습니다" in res.json()["detail"]


def test_chat_endpoint_success_and_context_accumulation():
    """정상 대화 시 DB에 로그가 저장되고 후속 질문에서 직전 대화가 컨텍스트로 주입되는지 검증"""
    headers = get_auth_headers("contextuser")

    with patch(
        "app.api.chat_router.call_ai_api",
        new=AsyncMock(side_effect=[("첫 번째 AI 답변", "SUCCESS"), ("두 번째 AI 답변", "SUCCESS")]),
    ) as mock_call_ai:
        res1 = client.post("/api/chat", json={"prompt": "  첫 번째 질문  "}, headers=headers)
        assert res1.status_code == 200
        body1 = res1.json()
        assert body1["prompt"] == "첫 번째 질문"
        assert body1["response"] == "첫 번째 AI 답변"
        assert body1["status"] == "SUCCESS"
        assert body1["context_used_count"] == 0

        res2 = client.post("/api/chat", json={"prompt": "두 번째 질문"}, headers=headers)
        assert res2.status_code == 200
        body2 = res2.json()
        assert body2["status"] == "SUCCESS"
        assert body2["context_used_count"] == 1

        second_call_messages = mock_call_ai.call_args_list[1].args[0]
        assert second_call_messages == [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "첫 번째 질문"},
            {"role": "assistant", "content": "첫 번째 AI 답변"},
            {"role": "user", "content": "두 번째 질문"},
        ]


def test_chat_endpoint_timeout_and_db_error_never_returns_500():
    """AI 타임아웃 또는 DB 저장 예외가 발생해도 500 에러 없이 200 OK와 안내 문구를 반환하는지 검증 (규칙 2)"""
    headers = get_auth_headers("resilienceuser")

    with patch(
        "app.api.chat_router.call_ai_api",
        new=AsyncMock(return_value=(FALLBACK_TIMEOUT_MESSAGE, "FAILED")),
    ), patch(
        "app.api.chat_router.save_chat_log",
        side_effect=RuntimeError("DB disk full simulated error"),
    ):
        res = client.post("/api/chat", json={"prompt": "타임아웃 및 DB 장애 테스트"}, headers=headers)

    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "FAILED"
    assert body["response"] == FALLBACK_TIMEOUT_MESSAGE
