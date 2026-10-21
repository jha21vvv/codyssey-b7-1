from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.logger import logger  # 안재현 팀원의 표준 로거 임포트
from app.models.user import User
from app.schemas.user import UserCreate, UserLogin, UserResponse, TokenResponse
from app.services.auth_service import hash_password, verify_password, create_access_token
from app.api.deps import get_current_user

router = APIRouter()

@router.post("/register", status_code=status.HTTP_201_CREATED)
def register_user(user_in: UserCreate, db: Session = Depends(get_db)):
    logger.info(f"[회원가입 시도] username={user_in.username}")
    
    # 중복 아이디 검사
    user = db.query(User).filter(User.username == user_in.username).first()
    if user:
        logger.warning(f"[회원가입 실패] 중복 아이디: username={user_in.username}")
        raise HTTPException(status_code=409, detail="이미 존재하는 아이디입니다.")
    
    # 새 유저 생성
    new_user = User(
        username=user_in.username,
        hashed_password=hash_password(user_in.password)
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    logger.info(f"[회원가입 성공] user_id={new_user.id}, username={new_user.username}")
    return {"message": "회원가입이 완료되었습니다."}