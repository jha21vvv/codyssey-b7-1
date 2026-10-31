from datetime import datetime, timezone

"""
[권태현] 시간 유틸
DB에 저장하는 시각을 timezone 정보 없는 UTC로 통일합니다 (chat_logs, request_logs 공용).
"""

def utc_now() -> datetime:
    # datetime.utcnow는 Python 3.12부터 deprecated라, 같은 값(timezone 정보 없는 UTC 시각)을 만드는 방식 사용
    return datetime.now(timezone.utc).replace(tzinfo=None)
