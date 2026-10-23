from typing import Any, Dict, List, Tuple
import httpx
from app.core.config import settings
from app.core.logger import logger

"""
[조명환 전담] AI 챗봇 비즈니스 로직, 입력 검증, 컨텍스트 빌더 및 비동기 API 클라이언트
과제 요구사항:
- 3. AI 챗봇 처리 (서버 사이드 호출, 컨텍스트 유지)
- 5. 운영 및 유지보수 (입력 검증, 타임아웃/장애 시 비정상 종료 방지, 필수 서버 로깅)
"""

MAX_PROMPT_LENGTH = 1000
SYSTEM_PROMPT = "당신은 Codyssey B7-1 친절하고 유능한 AI 어시스턴트입니다."
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
DEFAULT_GEMINI_MODEL = "gemini-flash-lite-latest"

FALLBACK_ERROR_MESSAGE = "현재 AI 서비스가 원활하지 않습니다. 잠시 후 다시 시도해주세요."
FALLBACK_TIMEOUT_MESSAGE = "AI 응답 시간이 초과되었습니다. 잠시 후 다시 질문해주세요."


def resolve_ai_endpoint_and_model() -> Tuple[str, str]:
    """
    AI_BASE_URL, AI_API_KEY 또는 AI_MODEL_NAME 설정에 따라 API 엔드포인트와 모델명을 결정합니다.
    - AI_BASE_URL이 설정된 경우: 해당 커스텀/프록시 엔드포인트(코디세이 콘솔 등) 사용
    - Gemini API 키(AIza... 또는 AQ....로 시작) 또는 gemini 모델명이 설정된 경우: Gemini 호환 엔드포인트 사용
    - 그 외의 경우: 기본 OpenAI 공식 엔드포인트 사용
    """
    api_key = (settings.AI_API_KEY or "").strip()
    configured_model = (settings.AI_MODEL_NAME or "gpt-4o-mini").strip()

    # 1. 커스텀 Base URL 지정 시 (코디세이 AI 프록시 등)
    if settings.AI_BASE_URL and settings.AI_BASE_URL.strip():
        base_url = settings.AI_BASE_URL.strip().rstrip("/")
        if not base_url.endswith("/chat/completions"):
            base_url = f"{base_url}/chat/completions"
        return base_url, configured_model

    # 2. Gemini API 키 또는 모델 지정 시
    is_gemini = api_key.startswith(("AIza", "AQ.")) or configured_model.lower().startswith("gemini")
    if is_gemini:
        model_name = (
            DEFAULT_GEMINI_MODEL
            if configured_model.lower().startswith("gpt-")
            else configured_model
        )
        return GEMINI_API_URL, model_name

    # 3. 기본 OpenAI 공식 엔드포인트
    return OPENAI_API_URL, configured_model


def validate_prompt(prompt: str) -> str:
    """
    [과제 요구사항 72-73] 사용자 입력 검증
    빈 입력, 공백만 있는 문자열 차단, 최대 1000자 초과 차단
    """
    if prompt is None:
        raise ValueError("질문 내용이 비어 있습니다. 텍스트를 입력해주세요.")
    clean_prompt = prompt.strip()
    if not clean_prompt:
        raise ValueError("질문 내용이 비어 있습니다. 텍스트를 입력해주세요.")
    if len(clean_prompt) > MAX_PROMPT_LENGTH:
        raise ValueError(f"질문은 최대 {MAX_PROMPT_LENGTH}자까지 입력 가능합니다.")
    return clean_prompt


def build_chat_context(recent_logs: List[Any], current_prompt: str) -> List[Dict[str, str]]:
    """
    [과제 요구사항 60-61] 최소한의 컨텍스트 구성 전략 (최근 N개의 대화 주입)
    recent_logs: 권태현의 ChatLog 객체 리스트 (최신순에서 역정렬하여 오래된 순으로 주입)
    """
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ]
    for log in reversed(recent_logs or []):
        if getattr(log, "status", None) == "SUCCESS":
            messages.append({"role": "user", "content": log.prompt})
            messages.append({"role": "assistant", "content": log.response})

    messages.append({"role": "user", "content": current_prompt})
    return messages


async def call_ai_api(messages: List[Dict[str, str]]) -> Tuple[str, str]:
    """
    [과제 요구사항 58, 70, 101] AI API 호출 및 타임아웃 방어
    Returns: (응답텍스트, 상태코드 문자열 "SUCCESS" | "FAILED")
    """
    api_url, model_name = resolve_ai_endpoint_and_model()
    logger.info(
        f"[AI 호출] [AI 호출 시작] 모델={model_name}, "
        f"메시지 수={len(messages)}, 타임아웃={settings.AI_TIMEOUT_SECONDS}초"
    )

    if not settings.AI_API_KEY or settings.AI_API_KEY.strip() in ("", "your-actual-api-key-here"):
        logger.error("[AI 응답 실패] [AI 호출 실패] 유효한 AI_API_KEY가 설정되지 않았습니다.")
        return FALLBACK_ERROR_MESSAGE, "FAILED"

    headers = {
        "Authorization": f"Bearer {settings.AI_API_KEY.strip()}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": 0.7,
    }

    try:
        async with httpx.AsyncClient(timeout=settings.AI_TIMEOUT_SECONDS) as client:
            res = await client.post(api_url, headers=headers, json=payload)
            if res.status_code == 200:
                data = res.json()
                reply = data["choices"][0]["message"]["content"]
                logger.info("[AI 응답 수신] [AI 응답 수신 성공] status=200")
                return reply, "SUCCESS"
            logger.error(f"[AI 응답 실패] [AI 호출 실패] 상태코드={res.status_code}, 본문={res.text}")
            return FALLBACK_ERROR_MESSAGE, "FAILED"
    except httpx.TimeoutException:
        logger.error(f"[AI 응답 실패] [AI 타임아웃] {settings.AI_TIMEOUT_SECONDS}초 초과")
        return FALLBACK_TIMEOUT_MESSAGE, "FAILED"
    except Exception as e:
        logger.error(f"[AI 응답 실패] [AI 통신 예외 발생] {str(e)}")
        return f"서비스 처리 중 일시적인 오류가 발생했습니다: {str(e)}", "FAILED"
