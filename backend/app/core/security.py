import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from cryptography.fernet import Fernet, InvalidToken

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
JWT_ALGORITHM = 'HS256'


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        password.encode(),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
    )
    return '$'.join(
        ['scrypt', base64.b64encode(salt).decode(), digest.hex()],
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_b64, digest_hex = stored.split('$')
    except ValueError:
        return False
    if scheme != 'scrypt':
        return False
    digest = hashlib.scrypt(
        password.encode(),
        salt=base64.b64decode(salt_b64),
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
    )
    return hmac.compare_digest(digest.hex(), digest_hex)


def load_or_create_key(path: Path) -> bytes:
    """Ключ для JWT и шифрования секретов.

    Создаётся при первом запуске в volume с данными, чтобы другу не
    пришлось ничего прописывать в .env. Потеря файла = потеря секретов в
    базе (их придётся ввести заново) и выход всех пользователей.
    """
    if path.exists():
        return path.read_bytes().strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    path.write_bytes(key)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return key


class SecretBox:
    """Шифрует секреты перед записью в базу."""

    def __init__(self, key: bytes) -> None:
        self._fernet = Fernet(key)
        self.signing_key = hashlib.sha256(b'jwt:' + key).hexdigest()

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken:
            return ''

    @classmethod
    def random(cls) -> 'SecretBox':
        return cls(Fernet.generate_key())


def create_token(box: SecretBox, username: str, ttl_hours: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        'sub': username,
        'iat': now,
        'exp': now + timedelta(hours=ttl_hours),
        'jti': secrets.token_hex(8),
    }
    return jwt.encode(payload, box.signing_key, algorithm=JWT_ALGORITHM)


def read_token(box: SecretBox, token: str) -> str | None:
    try:
        payload = jwt.decode(
            token,
            box.signing_key,
            algorithms=[JWT_ALGORITHM],
        )
    except jwt.PyJWTError:
        return None
    return payload.get('sub')


def mask(value: str) -> str:
    if not value:
        return ''
    return '…' + value[-4:] if len(value) > 8 else '…'
