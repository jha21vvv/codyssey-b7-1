"""
[조명환 전담] AI 챗봇 비즈니스 로직, 입력 검증, 컨텍스트 빌더 및 비동기 API 클라이언트
과제 요구사항:
- 3. AI 챗봇 처리 (서버 사이드 호출, 컨텍스트 유지)
- 5. 운영 및 유지보수 (입력 검증, 타임아웃/장애 시 비정상 종료 방지, 필수 서버 로깅)
"""

MAX_PROMPT_LENGTH = 1000


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
