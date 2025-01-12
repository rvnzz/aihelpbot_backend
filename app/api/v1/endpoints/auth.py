from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import timedelta
from app.core.config import settings
from app.core.security import create_access_token, get_current_user
from app.core.database import get_db
from app.crud import crud_user
from app.schemas.user import UserCreate, User
from pydantic import BaseModel
from typing import Any
from app.core import security


# Добавляем новую модель для ответа авторизации
class Token(BaseModel):
    access_token: str
    token_type: str


router = APIRouter()


@router.post(
    "/login",
    response_model=Token,
    responses={
        401: {"description": "Неверный email или пароль"},
    },
)
async def login(
    db: Session = Depends(get_db), form_data: OAuth2PasswordRequestForm = Depends()
):
    user = crud_user.authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный email или пароль",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(data={"sub": str(user.id)})
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/register", response_model=Token)
def register(user_in: UserCreate, db: Session = Depends(get_db)) -> Any:
    user = crud_user.get_user_by_email(db, email=user_in.email)
    if user:
        raise HTTPException(
            status_code=400, detail="Пользователь с таким email уже существует"
        )

    # Создаем нового пользователя
    user = crud_user.create_user(db, obj_in=user_in)

    # Создаем токен доступа
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id)}, expires_delta=access_token_expires
    )

    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/whoami", response_model=User)
async def whoami(current_user: User = Depends(get_current_user)):
    """
    Возвращает информацию о текущем авторизованном пользователе
    """
    return current_user
