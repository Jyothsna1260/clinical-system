from fastapi import APIRouter, Depends

from app.schemas.api import LoginRequest, RegisterRequest, TokenOut, UserOut
from app.security.deps import get_current_user
from app.services import auth
from app.storage import Store, UserRecord, get_store

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut, status_code=201)
def register(body: RegisterRequest, store: Store = Depends(get_store)) -> TokenOut:
    return auth.register(store, body.email, body.password, body.full_name)


@router.post("/login", response_model=TokenOut)
def login(body: LoginRequest, store: Store = Depends(get_store)) -> TokenOut:
    return auth.login(store, body.email, body.password)


@router.get("/me", response_model=UserOut)
def me(user: UserRecord = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)
