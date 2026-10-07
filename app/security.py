import bcrypt
import hashlib
import hmac
import secrets
from itsdangerous import URLSafeTimedSerializer
from app.config import settings

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))

def generate_session_token() -> str:
    return secrets.token_urlsafe(32)

def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()

def verify_token(provided_token: str, stored_hash: str) -> bool:
    provided_hash = hash_token(provided_token)
    return hmac.compare_digest(provided_hash, stored_hash)

def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)

def hash_csrf_token(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()

def verify_csrf_token(provided_token: str, stored_hash: str) -> bool:
    if not provided_token or not stored_hash:
        return False
    provided_hash = hash_csrf_token(provided_token)
    return hmac.compare_digest(provided_hash, stored_hash)

def get_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.SESSION_SECRET)