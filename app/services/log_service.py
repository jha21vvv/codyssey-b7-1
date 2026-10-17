from typing import List
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

def get_user_chat_logs(user_id: int, limit: int, db: Session) -> List[ChatLog]:
    """
    [조명환의 컨텍스트 빌더용] 해당 사용자의 가장 최근 대화 N개를 최신순으로 반환
    """
    return (
        db.query(ChatLog)
        .filter(ChatLog.user_id == user_id)
        # [안내서 대비 변경] 저장 시각이 같으면 순서가 보장되지 않아 id를 보조 정렬 기준으로 추가
        .order_by(ChatLog.created_at.desc(), ChatLog.id.desc())
        .limit(limit)
        .all()
    )

# [안내서 대비 변경] 안내서 시그니처는 (skip=0, limit=100, db=None)이지만,
# db 없이 호출되면 내부에서 AttributeError가 나므로 세 인자를 모두 필수로 받음
# (skip/limit 기본값은 로그 조회 라우터에서 지정)
def get_all_chat_logs(skip: int, limit: int, db: Session) -> List[ChatLog]:
    """
    [관리자/평가자 확인용] 전체 사용자의 대화 로그를 최신순으로 페이지 단위 조회
    """
    return (
        db.query(ChatLog)
        # [안내서 대비 변경] get_user_chat_logs와 같은 기준으로 정렬 (같은 시각이면 id 역순)
        .order_by(ChatLog.created_at.desc(), ChatLog.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
