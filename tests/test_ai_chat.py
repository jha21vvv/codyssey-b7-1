import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest
from pydantic import ValidationError
from app.core.config import settings
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.ai_service import (
    FALLBACK_ERROR_MESSAGE,
    FALLBACK_TIMEOUT_MESSAGE,
    SYSTEM_PROMPT,
    build_chat_context,
    call_ai_api,
    validate_prompt,
)

"""
[조명환 전담] AI 파이프라인(입력 검증, 컨텍스트 조립, 비동기 AI 호출 및 타임아웃 방어) 단위 테스트
"""


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
    """공백이나 줄바꿈만 있는 질문 차단 검증 (과제 요구사항 72~73)"""
    with pytest.raises(ValueError, match="비어 있습니다"):
        validate_prompt("     \n\t  ")


def test_validate_prompt_max_length_exceeded():
    """1,000자 초과 질문 차단 검증 (과제 요구사항 72~73)"""
    long_prompt = "가" * 1001
    with pytest.raises(ValueError, match="최대 1000자"):
        validate_prompt(long_prompt)


def test_build_chat_context_chronological_and_filter_failed():
    """
    최근 N개 대화 이력(최신순 조회 결과)을 시간순(역순)으로 조립하고,
    FAILED 상태 로그는 컨텍스트에서 제외하는지 검증 (과제 요구사항 60~61)
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

