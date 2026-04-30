import pytest
from cryptography.fernet import InvalidToken
from app.auth.tokens import encrypt, decrypt


def test_encrypt_decrypt_roundtrip():
    original = "ghp_test_token_12345"
    assert decrypt(encrypt(original)) == original


def test_decrypt_invalid_raises():
    with pytest.raises(InvalidToken):
        decrypt("not-valid-ciphertext")
