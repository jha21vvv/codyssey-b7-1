import argparse
import sqlite3
from pathlib import Path
from typing import Optional

"""
[권태현 전담] 평가자 확인용 SQLite 대화 로그 조회 스크립트
서버가 만든 chat_service.db를 읽기 전용으로 열어 최근 대화 로그를 사용자 이름과 함께 출력합니다.

사용 예 (저장소 루트에서 실행):
    python scripts/verify_logs.py                  # 최근 5건
    python scripts/verify_logs.py --limit 20       # 최근 20건
    python scripts/verify_logs.py --user alice     # 특정 사용자의 로그만
    python scripts/verify_logs.py --db ./other.db  # 다른 DB 파일 지정
"""

# [안내서 대비 변경] 안내서의 상대 경로("chat_service.db")는 실행 위치에 따라 DB를 못 찾으므로
# 스크립트 위치 기준으로 저장소 루트의 DB를 가리킴 (서버를 저장소 루트에서 실행했을 때의 DATABASE_URL 기본값)
DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "chat_service.db"
PREVIEW_LENGTH = 100

def preview(text: str) -> str:
    """긴 질문/응답은 한 줄로 줄이고 PREVIEW_LENGTH자까지만 표시"""
    # [안내서 대비 변경] 안내서는 응답만 100자로 잘랐지만, 질문도 함께 자르고 줄바꿈을 합쳐 출력이 길어지지 않게 함
    one_line = " ".join(text.split())
    if len(one_line) > PREVIEW_LENGTH:
        return one_line[:PREVIEW_LENGTH] + "..."
    return one_line

def verify_db(db_path: Path, limit: int, username: Optional[str]) -> None:
    if not db_path.exists():
        print(f"[ERROR] DB 파일({db_path})이 존재하지 않습니다. 먼저 서버를 실행하고 대화를 진행하세요.")
        return

    # [안내서 대비 변경] 확인 과정에서 DB가 바뀌지 않도록 읽기 전용으로 연결
    conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        cur = conn.cursor()
        # 사용자 이름은 쿼리 파라미터로만 전달 (SQL 인젝션 방지)
        where = "WHERE u.username = ?" if username else ""
        params = [username] if username else []

        # [안내서 대비 변경] 출력 개수와 별개로 전체 저장 건수도 함께 표시
        cur.execute(f"SELECT COUNT(*) FROM chat_logs c JOIN users u ON c.user_id = u.id {where}", params)
        total = cur.fetchone()[0]

        # [안내서 대비 변경] 같은 시각이면 id 역순으로 정렬해 log_service와 같은 순서로 출력
        cur.execute(f"""
            SELECT c.id, u.username, c.prompt, c.response, c.status, c.created_at
            FROM chat_logs c
            JOIN users u ON c.user_id = u.id
            {where}
            ORDER BY c.created_at DESC, c.id DESC
            LIMIT ?
        """, params + [limit])
        rows = cur.fetchall()
    except sqlite3.OperationalError as e:
        # [안내서 대비 변경] 테이블이 아직 없으면 traceback 대신 안내 메시지 출력
        print(f"[ERROR] 대화 로그를 조회할 수 없습니다: {e}")
        print("        서버를 한 번 실행해 users, chat_logs 테이블이 생성된 뒤 다시 시도하세요.")
        return
    finally:
        conn.close()

    # [안내서 대비 변경] 이모지는 cp949 환경(한국어 Windows의 Git Bash, 출력 리디렉션)에서
    # UnicodeEncodeError가 날 수 있어 사용하지 않음
    print("\n" + "=" * 80)
    print(" [평가자 확인 가이드] Codyssey B7-1 SQLite 대화 로그 검증")
    print("=" * 80)
    print(f"DB 파일: {db_path}")
    print(f"대상: {username or '전체 사용자'} | 저장된 로그: {total}건 | 최근 {len(rows)}건 출력")
    print("-" * 80)

    if not rows:
        print(">> 저장된 대화 로그가 없습니다.")
        return

    for log_id, user, prompt, response, status, created_at in rows:
        print(f"[Log ID: {log_id}] 유저: {user} | 상태: {status} | 시각(UTC): {created_at}")
        print(f" Q: {preview(prompt)}")
        print(f" A: {preview(response)}")
        print("-" * 80)

if __name__ == "__main__":
    # [안내서 대비 변경] 안내서는 최근 5건 고정 출력이라 DB 경로, 출력 개수, 사용자 필터 옵션을 추가
    parser = argparse.ArgumentParser(description="Codyssey B7-1 SQLite 대화 로그 확인 스크립트")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="SQLite DB 파일 경로")
    parser.add_argument("--limit", type=int, default=5, help="출력할 최근 로그 수 (기본 5)")
    parser.add_argument("--user", help="이 사용자 이름(username)의 로그만 출력")
    args = parser.parse_args()

    verify_db(args.db, args.limit, args.user)
