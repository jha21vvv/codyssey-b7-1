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

@router.post("/login", response_model=TokenResponse)
def login_user(user_in: UserLogin, db: Session = Depends(get_db)):
    logger.info(f"[로그인 시도] username={user_in.username}")
    
    user = db.query(User).filter(User.username == user_in.username).first()
    if not user or not verify_password(user_in.password, user.hashed_password):
        logger.warning(f"[로그인 실패] 인증 정보 불일치: username={user_in.username}")
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다.")
    
    access_token = create_access_token(data={"sub": user.username})
    
    logger.info(f"[로그인 성공] user_id={user.id}, username={user.username}")
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user
    }

@router.post("/logout")
def logout_user():
    logger.info("[로그아웃 요청 완료]")
    return {"message": "로그아웃 되었습니다. 클라이언트에서 토큰을 삭제해주세요."}

@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user