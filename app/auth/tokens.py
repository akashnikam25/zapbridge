from cryptography.fernet import Fernet
from app.config import settings

_fernet = Fernet(settings.FERNET_KEY.encode())


def encrypt(token: str) -> str:
    return _fernet.encrypt(token.encode()).decode()


def decrypt(encrypted: str) -> str:
    return _fernet.decrypt(encrypted.encode()).decode()
