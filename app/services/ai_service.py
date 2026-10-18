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


def validate_prompt(prompt: str) -> str:
    """
    [과제 요구사항 72~73] 사용자 입력 검증
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
    [과제 요구사항 60~61] 최소한의 컨텍스트 구성 전략 (최근 N개의 대화 주입)
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
    logger.info(
        f"[AI 호출] [AI 호출 시작] 모델={settings.AI_MODEL_NAME}, "
        f"메시지 수={len(messages)}, 타임아웃={settings.AI_TIMEOUT_SECONDS}초"
    )

    headers = {
        "Authorization": f"Bearer {settings.AI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.AI_MODEL_NAME,
        "messages": messages,
        "temperature": 0.7,
    }

    async with httpx.AsyncClient(timeout=settings.AI_TIMEOUT_SECONDS) as client:
        res = await client.post(OPENAI_API_URL, headers=headers, json=payload)
        if res.status_code == 200:
            data = res.json()
            reply = data["choices"][0]["message"]["content"]
            logger.info("[AI 응답 수신] [AI 응답 수신 성공] status=200")
            return reply, "SUCCESS"
        logger.error(f"[AI 응답 실패] [AI 호출 실패] 상태코드={res.status_code}, 본문={res.text}")
        return "현재 AI 서비스가 원활하지 않습니다. 잠시 후 다시 시도해주세요.", "FAILED"


