import threading

from fastapi import APIRouter, Depends

from app.api.errors import AppError
from app.schemas.api import LoginRequest, RegisterRequest, TokenOut, UserOut
from app.security.deps import get_current_user
from app.security.jwt import create_access_token, hash_password, verify_password
from app.services import audit
from app.storage import Store, UserRecord, get_store

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Makes the email-uniqueness check and the write a single step.
_register_lock = threading.Lock()


@router.post("/register", response_model=TokenOut, status_code=201)
def register(body: RegisterRequest, store: Store = Depends(get_store)) -> TokenOut:
    email = body.email.lower()
    hashed = hash_password(body.password)
    with _register_lock:
        if store.user_by_email(email):
            raise AppError(409, "EMAIL_TAKEN", "An account with this email already exists.")
        user = store.users.put(UserRecord(email=email, hashed_password=hashed, full_name=body.full_name))
    audit.record(store, user.id, "user.registered", "user", user.id)
    return TokenOut(access_token=create_access_token(user.id), user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenOut)
def login(body: LoginRequest, store: Store = Depends(get_store)) -> TokenOut:
    user = store.user_by_email(body.email)
    if user is None or not verify_password(body.password, user.hashed_password):
        raise AppError(401, "INVALID_CREDENTIALS", "Email or password is incorrect.")
    audit.record(store, user.id, "user.login", "user", user.id)
    return TokenOut(access_token=create_access_token(user.id), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: UserRecord = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)
