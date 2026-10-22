from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.logger import logger
from app.models.user import User
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.ai_service import build_chat_context, call_ai_api, validate_prompt
from app.services.log_service import get_user_chat_logs, save_chat_log

"""
[조명환 전담] AI 챗봇 메인 엔드포인트 (POST /api/chat)
전체 파이프라인 오케스트레이션:
1. 비로그인 사용자 접근 차단 (신재은의 get_current_user 의존성 -> 401 반환)
2. 사용자 질문 입력값 유효성 검증 (공백 문자열 차단, 최대 1000자 제한 -> 422 반환)
3. 최근 3개 대화 이력 조회 및 시간순 컨텍스트 조립 (권태현의 get_user_chat_logs 연동)
4. 비동기 AI API 호출 및 타임아웃/장애 방어 (비정상 종료 500 에러 원천 차단)
5. 질문·응답 DB 누적 저장 및 [DB 저장 성공]/[DB 저장 실패] 필수 서버 로깅 (권태현의 save_chat_log 연동)
"""

router = APIRouter()


@router.post("", response_model=ChatResponse)
async def chat_endpoint(
    req: ChatRequest,
    current_user: User = Depends(get_current_user),  # 비로그인 시 401 자동 차단
    db: Session = Depends(get_db),
):
    # 1. 입력 검증 (공백만 있는 질문 등 차단)
    try:
        valid_prompt = validate_prompt(req.prompt)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )

    # 2. 직전 N개 대화 조회 (권태현 함수)
    recent_logs = get_user_chat_logs(user_id=current_user.id, limit=3, db=db)

    # 3. 컨텍스트 구성
    context_messages = build_chat_context(recent_logs=recent_logs, current_prompt=valid_prompt)

    # 4. AI API 호출 (타임아웃 방어)
    ai_reply, status_code = await call_ai_api(context_messages)

    # 5. DB 대화 로그 저장 (권태현 함수) & 필수 로깅
    try:
        save_chat_log(
            user_id=current_user.id,
            prompt=valid_prompt,
            response=ai_reply,
            status=status_code,
            db=db,
        )
        logger.info(f"[DB 저장 성공] user_id={current_user.id}, status={status_code}")
    except Exception as db_err:
        logger.error(f"[DB 저장 실패] user_id={current_user.id}, 사유={str(db_err)}")
        # DB 저장이 실패해도 사용자 채팅 서비스 자체가 죽지 않도록 방어

    # 6. 응답 반환 (절대 500 Internal Server Error로 비정상 종료되지 않음)
    return ChatResponse(
        prompt=valid_prompt,
        response=ai_reply,
        status=status_code,
        context_used_count=len(recent_logs),
    )
