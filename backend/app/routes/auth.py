from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models.user import User
from app.core.security import decode_access_token, hash_password, verify_password, create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    first_name: str
    last_name: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

@router.post("/register")
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == payload.email))
    if result.scalar_one_or_none():
        raise HTTPException(400, "Email already registered")

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        first_name=payload.first_name,
        last_name=payload.last_name,
    )
    db.add(user)
    await db.commit()
    return {"message": "User created"}

@router.post("/login")
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")

    token = create_access_token({"sub": str(user.id)})
    return {"access_token": token, "token_type": "bearer"}



oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception

    # Usually stored under "sub" (either user email or user ID)
    user_id_or_email = payload.get("sub")
    if user_id_or_email is None:
        raise credentials_exception

    # Query the user from PostgreSQL
    if str(user_id_or_email).isdigit():
        stmt = select(User).where(User.id == int(user_id_or_email))
    else:
        stmt = select(User).where(User.email == str(user_id_or_email))

    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception

    return user