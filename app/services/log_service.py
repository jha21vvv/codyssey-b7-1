from sqlalchemy.orm import Session
from app.models.chat_log import ChatLog

"""
[권태현 전담] 대화 로그 저장 및 조회 서비스
조명환의 chat_router(POST /api/chat)가 AI 호출 전후로 호출하며,
로그 조회 API(/api/logs)에서도 사용합니다.
"""

def save_chat_log(user_id: int, prompt: str, response: str, status: str, db: Session) -> ChatLog:
    """
    [과제 요구사항: 대화 로그 누적 저장] 사용자 질문과 AI 응답을 DB에 저장
    저장에 실패하면 세션을 롤백한 뒤 예외를 그대로 올려,
    호출 측(chat_router)이 [DB 저장 실패] 로그를 남길 수 있게 합니다.
    """
    log = ChatLog(
        user_id=user_id,
        prompt=prompt,
        response=response,
        status=status,
    )
    # [안내서 대비 변경] 안내서 코드에 없는 롤백 추가: 저장에 실패해도 같은 세션을 계속 쓸 수 있게 함
    try:
        db.add(log)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(log)
    return log
