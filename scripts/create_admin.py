import argparse
import getpass
import sys
from pathlib import Path
from typing import List, Optional

# Windows 콘솔 및 리디렉션 환경에서 UTF-8 한글 출력 보장
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# scripts 폴더에서 실행해도 저장소 루트의 app 패키지를 가져올 수 있게 함
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pydantic import ValidationError  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from app.core.database import Base  # noqa: E402
from app.core.errors import validation_message  # noqa: E402
from app.core.logger import logger  # noqa: E402
from app.core.migrations import upgrade_schema  # noqa: E402
from app.models import chat_log, request_log  # noqa: E402,F401  (create_all이 모든 테이블을 알도록 등록)
from app.models.user import ADMIN_ROLE, USER_ROLE, User  # noqa: E402
from app.schemas.user import UserCreate  # noqa: E402
from app.services.admin_service import create_user_with_role, list_admins, set_user_role  # noqa: E402

"""
[권태현 전담] 관리자 계정 지정·해제 스크립트
관리자는 웹에서 스스로 될 수 없고, 서버(DB 파일)에 접근할 수 있는 운영자만 이 스크립트로 지정합니다.

사용 예 (저장소 루트에서 실행):
    python scripts/create_admin.py alice            # 가입한 alice를 관리자로 지정 (없는 아이디면 비밀번호를 입력받아 새로 만듦)
    python scripts/create_admin.py alice --revoke   # alice의 관리자 권한 해제 (일반 사용자로)
    python scripts/create_admin.py --list           # 관리자 목록
    python scripts/create_admin.py alice --db ./other.db  # 다른 DB 파일 지정
"""

# verify_logs.py와 같이 서버를 저장소 루트에서 실행했을 때의 DB 파일
DEFAULT_DB_PATH = ROOT / "chat_service.db"
# 아이디 규칙만 먼저 검사할 때 넣는 임시 비밀번호 (저장하지 않음)
USERNAME_CHECK_PASSWORD = "check-username-only"


def account_errors(username: str, password: str) -> List[str]:
    """회원가입(UserCreate)과 같은 규칙으로 아이디·비밀번호를 검사해 한국어 안내 목록을 돌려줌"""
    try:
        UserCreate(username=username, password=password)
    except ValidationError as e:
        return list(dict.fromkeys(validation_message(error) for error in e.errors()))
    return []


def ask_new_password() -> Optional[str]:
    password = getpass.getpass("새 관리자 계정의 비밀번호: ")
    if getpass.getpass("비밀번호 확인: ") != password:
        print("[ERROR] 두 비밀번호가 다릅니다.")
        return None
    return password


def grant(db, username: str) -> int:
    user = db.query(User).filter(User.username == username).first()
    if user is not None:
        if user.role == ADMIN_ROLE:
            print(f"{username}은(는) 이미 관리자입니다.")
            return 0
        set_user_role(db, username, ADMIN_ROLE)
        logger.info(f"[관리자 지정] user_id={user.id}, username={username}")
        return 0

    # 없는 아이디: 아이디 규칙을 먼저 확인한 뒤 비밀번호를 입력받아 새 관리자 계정을 만듦
    errors = account_errors(username, USERNAME_CHECK_PASSWORD)
    if errors:
        print("[ERROR] " + " ".join(errors))
        return 1
    print(f"{username} 계정이 없어 새 관리자 계정을 만듭니다.")
    password = ask_new_password()
    if password is None:
        return 1
    errors = account_errors(username, password)
    if errors:
        print("[ERROR] " + " ".join(errors))
        return 1
    user = create_user_with_role(db, username, password, ADMIN_ROLE)
    logger.info(f"[관리자 계정 생성] user_id={user.id}, username={username}")
    return 0


def revoke(db, username: str) -> int:
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        print(f"[ERROR] {username} 계정이 없습니다.")
        return 1
    if user.role != ADMIN_ROLE:
        print(f"{username}은(는) 관리자가 아닙니다.")
        return 0
    set_user_role(db, username, USER_ROLE)
    logger.info(f"[관리자 해제] user_id={user.id}, username={username}")
    return 0


def show_admins(db) -> int:
    admins = list_admins(db)
    if not admins:
        print("관리자가 없습니다. python scripts/create_admin.py <아이디> 로 지정하세요.")
        return 0
    print(f"관리자 {len(admins)}명: " + ", ".join(f"{admin.username}(id={admin.id})" for admin in admins))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Codyssey B7-1 관리자 계정 지정·해제")
    parser.add_argument("username", nargs="?", help="관리자로 지정하거나 해제할 아이디")
    parser.add_argument("--revoke", action="store_true", help="관리자 권한 해제 (일반 사용자로)")
    parser.add_argument("--list", action="store_true", help="관리자 목록 보기")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="SQLite DB 파일 경로")
    args = parser.parse_args(argv)
    if not args.list and not args.username:
        parser.error("아이디를 입력하세요. 예: python scripts/create_admin.py alice")

    if not args.db.exists():
        # 경로를 잘못 적어 엉뚱한 곳에 빈 DB가 생기지 않도록, 새로 만들지 않고 안내만 함
        print(f"[ERROR] DB 파일({args.db})이 없습니다. 서버를 한 번 실행해 DB를 만든 뒤 다시 실행하세요.")
        return 1

    print(f"DB 파일: {args.db}")
    engine = create_engine(f"sqlite:///{args.db}", connect_args={"check_same_thread": False})
    try:
        # 서버를 아직 새 버전으로 실행하지 않은 DB라도 role 컬럼 등을 먼저 맞춤 (서버 시작 때와 같은 처리)
        Base.metadata.create_all(bind=engine)
        upgrade_schema(engine)
        db = sessionmaker(bind=engine)()
        try:
            if args.list:
                return show_admins(db)
            if args.revoke:
                return revoke(db, args.username)
            result = grant(db, args.username)
            if result == 0:
                print("관리자 화면: 서버 주소 뒤에 /admin (예: http://localhost:8080/admin)")
            return result
        finally:
            db.close()
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
