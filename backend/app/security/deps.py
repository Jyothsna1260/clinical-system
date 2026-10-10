"""FastAPI dependencies for authentication."""

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.errors import AppError
from app.security.jwt import decode_access_token
from app.storage import Store, UserRecord, get_store

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    store: Store = Depends(get_store),
) -> UserRecord:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError(401, "UNAUTHENTICATED", "Missing bearer token.")
    user_id = decode_access_token(credentials.credentials)
    if user_id is None:
        raise AppError(401, "INVALID_TOKEN", "Token is invalid or expired.")
    user = store.users.get(user_id)
    if user is None:
        raise AppError(401, "INVALID_TOKEN", "User no longer exists.")
    return user
