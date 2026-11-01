import time
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.errors import ApiError, ErrorResponse, error_response
from app.core.logger import logger
from app.models.user import User
from app.schemas.chat import ChatFailureResponse, ChatRequest, ChatResponse
from app.services.ai_service import build_chat_context, call_ai_api, validate_prompt
from app.services.log_service import get_user_chat_logs, save_chat_log

"""
[조명환 전담] AI 챗봇 메인 엔드포인트 (POST /api/chat)
전체 파이프라인 오케스트레이션:
1. 비로그인 사용자 접근 차단 (신재은의 get_current_user 의존성 -> 401 반환)
2. 사용자 질문 입력값 유효성 검증 (공백 문자열 차단, 최대 1000자 제한 -> 422 반환)
3. 최근 3개 대화 이력 조회 및 시간순 컨텍스트 조립 (권태현의 get_user_chat_logs 연동)
4. 비동기 AI API 호출 및 타임아웃/장애 방어 (서버는 멈추지 않고, 장애 원인별 상태 코드와 안내 문구 반환)
5. 질문·응답 DB 누적 저장 및 [DB 저장 성공]/[DB 저장 실패] 필수 서버 로깅 (권태현의 save_chat_log 연동)
"""

router = APIRouter()

# [권태현] AI 실패 종류별 상태 코드와 오류 코드
# 타임아웃은 504, AI 쪽 오류는 502, AI 키 미설정은 503 (모두 안내 문구와 함께 응답하고 대화는 FAILED로 저장)
AI_FAILURE_RESPONSES = {
    "TIMEOUT": (504, "AI_TIMEOUT"),
    "NOT_CONFIGURED": (503, "AI_NOT_CONFIGURED"),
    "UPSTREAM_ERROR": (502, "AI_UPSTREAM_ERROR"),
    "BAD_RESPONSE": (502, "AI_BAD_RESPONSE"),
    "CONNECTION_ERROR": (502, "AI_CONNECTION_ERROR"),
    "UNEXPECTED_ERROR": (502, "AI_UNEXPECTED_ERROR"),
}

CHAT_ERROR_DOCS = {
    401: {"model": ErrorResponse, "description": "로그인 필요"},
    422: {"model": ErrorResponse, "description": "질문이 비었거나 1000자 초과"},
    502: {"model": ChatFailureResponse, "description": "AI 서버 오류·응답 형식 오류·연결 실패"},
    503: {"model": ChatFailureResponse, "description": "AI 키 미설정"},
    504: {"model": ChatFailureResponse, "description": "AI 응답 시간 초과"},
}


def _db_error_reason(error: Exception) -> str:
    """
    [권태현] DB 오류 원인만 짧게 반환
    SQLAlchemy 예외 문자열에는 질문 내용이 든 SQL 파라미터가 섞여 있어 서버 로그에 그대로 남기지 않음
    """
    original = getattr(error, "orig", None)
    return f"{type(error).__name__}: {original}" if original is not None else type(error).__name__


@router.post("", response_model=ChatResponse, responses=CHAT_ERROR_DOCS)
async def chat_endpoint(
    req: ChatRequest,
    request: Request,
    current_user: User = Depends(get_current_user),  # 비로그인 시 401 자동 차단
    db: Session = Depends(get_db),
):
    # 1. 입력 검증 (공백만 있는 질문 등 차단)
    try:
        valid_prompt = validate_prompt(req.prompt)
    except ValueError as e:
        raise ApiError(422, "PROMPT_INVALID", str(e))

    # 2. 직전 N개 대화 조회 (권태현 함수)
    recent_logs = get_user_chat_logs(user_id=current_user.id, limit=3, db=db)

    # 3. 컨텍스트 구성 (FAILED 대화는 빠지므로, 실제로 들어간 SUCCESS 대화 수를 응답에 알려 줌)
    context_messages = build_chat_context(recent_logs=recent_logs, current_prompt=valid_prompt)
    context_used_count = sum(1 for log in recent_logs if log.status == "SUCCESS")

    # 4. AI API 호출 (타임아웃 방어) + 걸린 시간 측정
    started = time.perf_counter()
    result = await call_ai_api(context_messages)
    latency_ms = int((time.perf_counter() - started) * 1000)

    # 5. DB 대화 로그 저장 (권태현 함수) & 필수 로깅
    try:
        save_chat_log(
            user_id=current_user.id,
            prompt=valid_prompt,
            response=result.reply,
            status=result.status,
            db=db,
            request_id=getattr(request.state, "req_id", None),
            latency_ms=latency_ms,
            error_type=result.error_type,
        )
        logger.info(f"[DB 저장 성공] user_id={current_user.id}, status={result.status}, AI 응답 시간={latency_ms}ms")
    except Exception as db_err:
        logger.error(f"[DB 저장 실패] user_id={current_user.id}, 사유={_db_error_reason(db_err)}")
        # DB 저장이 실패해도 사용자 채팅 서비스 자체가 죽지 않도록 방어

    # 6. 응답 반환 (서버는 멈추지 않고, AI 장애면 원인에 맞는 상태 코드와 안내 문구를 보냄)
    if result.status == "SUCCESS":
        return ChatResponse(
            prompt=valid_prompt,
            response=result.reply,
            status="SUCCESS",
            context_used_count=context_used_count,
        )
    status_code, code = AI_FAILURE_RESPONSES.get(result.error_type, (502, "AI_UPSTREAM_ERROR"))
    return error_response(
        request,
        status_code,
        result.reply,
        code,
        prompt=valid_prompt,
        response=result.reply,
        status="FAILED",
        context_used_count=context_used_count,
    )
