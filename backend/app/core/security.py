
from datetime import datetime, timedelta, timezone

from jose import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.bcrypt import BcryptHasher

from app.core.config import settings

pwd_hash = PasswordHash((BcryptHasher(),))

def _truncate_password(password: str) -> str:
    # bcrypt only supports passwords up to 72 bytes.
    return password.encode("utf-8")[:72].decode("utf-8", errors="ignore")


def hash_password(password: str) -> str:
    return pwd_hash.hash(_truncate_password(password))


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_hash.verify(
        _truncate_password(plain_password),
        hashed_password,
    )


def create_access_token(data: dict) -> str:
    to_encode = data.copy()

    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )

    to_encode.update({"exp": expire})

    return jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm="HS256",
    )


def decode_access_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=["HS256"],
        )
        return payload
    except jwt.JWTError:
        return None