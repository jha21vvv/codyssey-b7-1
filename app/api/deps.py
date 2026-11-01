from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.config import settings
from app.core.errors import ApiError
from app.core.logger import logger
from app.models.user import ADMIN_ROLE, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

def get_current_user(request: Request, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="로그인이 필요한 서비스입니다.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exception
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
        
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception
    request.state.user_id = user.id  # [권태현] 요청 로그(request_logs)에 누가 보낸 요청인지 남김
    return user

def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    """
    [권태현] 관리자만 통과하는 권한 검사 (관리자 API에서 사용)
    - 로그인하지 않았거나 토큰이 잘못되면 get_current_user가 401로 막음 (인증: 누구인지 확인)
    - 로그인했지만 관리자가 아니면 403으로 막음 (권한: 이 기능을 써도 되는지 확인)
    역할은 토큰이 아니라 DB에서 매번 읽으므로, 관리자 권한을 해제하면 다음 요청부터 바로 막힘
    """
    if current_user.role != ADMIN_ROLE:
        logger.warning(f"[관리자 권한 거부] user_id={current_user.id}")
        raise ApiError(403, "ADMIN_REQUIRED", "관리자만 사용할 수 있는 기능입니다.")
    return current_user
