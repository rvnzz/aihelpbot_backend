from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.core.dependencies import check_admin_permission
from app.crud import crud_user
from app.schemas.user import User, UserCreate, UserUpdate
from app.models.user import UserRole

router = APIRouter()

@router.post("/managers", response_model=User)
async def create_manager(
    user: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(check_admin_permission)
):
    db_user = crud_user.get_user_by_email(db, email=user.email)
    if db_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email уже зарегистрирован"
        )
    user.role = UserRole.MANAGER
    return crud_user.create_user(db=db, user=user)

@router.get("/users", response_model=List[User])
async def read_users(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(check_admin_permission)
):
    users = crud_user.get_users(db, skip=skip, limit=limit)
    return users 