from types import SimpleNamespace
import pytest
from pydantic import ValidationError
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.ai_service import (
    SYSTEM_PROMPT,
    build_chat_context,
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
