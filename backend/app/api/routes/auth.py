from fastapi import APIRouter, Depends, Request

from app.schemas.api import LoginRequest, RegisterRequest, TokenOut, UserOut
from app.security import rate_limit
from app.security.deps import get_current_user
from app.services import auth
from app.storage import Store, UserRecord, get_store

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut, status_code=201)
def register(body: RegisterRequest, request: Request, store: Store = Depends(get_store)) -> TokenOut:
    rate_limit.enforce("register", rate_limit.client_ip(request))
    return auth.register(store, body.email, body.password, body.full_name)


@router.post("/login", response_model=TokenOut)
def login(body: LoginRequest, request: Request, store: Store = Depends(get_store)) -> TokenOut:
    # Per IP (bulk guessing) and per account (targeted guessing from many addresses).
    rate_limit.enforce("login", rate_limit.client_ip(request), body.email.lower())
    return auth.login(store, body.email, body.password)


@router.get("/me", response_model=UserOut)
def me(user: UserRecord = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)
