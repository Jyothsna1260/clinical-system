"""Use cases: register an account and sign in."""

import threading

from app.errors import AppError
from app.schemas.api import TokenOut, UserOut
from app.security.jwt import create_access_token, hash_password, verify_password
from app.services import audit
from app.storage import Store, UserRecord

# Makes the email-uniqueness check and the write a single step.
_register_lock = threading.Lock()


def _token_for(user: UserRecord) -> TokenOut:
    return TokenOut(access_token=create_access_token(user.id), user=UserOut.model_validate(user))


def register(store: Store, email: str, password: str, full_name: str | None) -> TokenOut:
    email = email.lower()
    hashed = hash_password(password)
    with _register_lock:
        if store.user_by_email(email):
            raise AppError(409, "EMAIL_TAKEN", "An account with this email already exists.")
        user = store.users.put(UserRecord(email=email, hashed_password=hashed, full_name=full_name))
    audit.record(store, user.id, "user.registered", "user", user.id)
    return _token_for(user)


def login(store: Store, email: str, password: str) -> TokenOut:
    user = store.user_by_email(email)
    if user is None or not verify_password(password, user.hashed_password):
        raise AppError(401, "INVALID_CREDENTIALS", "Email or password is incorrect.")
    audit.record(store, user.id, "user.login", "user", user.id)
    return _token_for(user)
