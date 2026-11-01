from pydantic import BaseModel, Field, field_validator
import re

class UserCreate(BaseModel):
    # 영문 대소문자와 숫자만 허용하는 정규식 추가
    username: str = Field(
        ..., 
        min_length=3, 
        max_length=50, 
        pattern=r"^[a-zA-Z0-9]+$", 
        description="사용자 아이디 (영문, 숫자만 허용)"
    )
    password: str = Field(
        ..., 
        min_length=4, 
        max_length=100, 
        description="비밀번호"
    )

    # 스페이스바(공백)로만 4칸 이상 채운 비밀번호 차단
    @field_validator('password')
    @classmethod
    def password_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("비밀번호는 공백으로만 구성될 수 없습니다.")
        return v

class UserLogin(BaseModel):
    username: str
    password: str

class UserResponse(BaseModel):
    id: int
    username: str
    role: str  # [권태현] "user" 또는 "admin" (웹 화면이 관리자에게만 관리자 화면 링크를 보여줄 때 사용)

    class Config:
        from_attributes = True

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse