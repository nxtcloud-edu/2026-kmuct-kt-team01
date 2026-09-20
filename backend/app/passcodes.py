"""앨범 참여 비밀번호 해싱.

When2meet 처럼 "이름 + 비밀번호"로 본인을 확인해 같은 멤버로 다시 들어오게 한다.
계정 시스템이 아니라 앨범 하나 안에서의 본인 확인이므로 이메일·아이디는 없다.

표준 라이브러리만 쓴다(pbkdf2_hmac). bcrypt/argon2 를 새로 의존성에 넣지 않으려는
의도적인 선택이고, 저장 형식에 알고리즘과 반복 횟수를 함께 적어 나중에 바꿀 수 있게 했다.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

__all__ = ["MIN_PASSCODE_LENGTH", "MAX_PASSCODE_LENGTH", "hash_passcode", "verify_passcode"]

MIN_PASSCODE_LENGTH = 4
MAX_PASSCODE_LENGTH = 64

_ALGORITHM = "pbkdf2_sha256"
_ITERATIONS = 200_000
_SALT_BYTES = 16


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _derive(passcode: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", passcode.encode("utf-8"), salt, iterations)


def hash_passcode(passcode: str) -> str:
    """`pbkdf2_sha256$반복횟수$솔트$해시` 형식의 한 줄 문자열을 돌려준다."""
    salt = secrets.token_bytes(_SALT_BYTES)
    derived = _derive(passcode, salt, _ITERATIONS)
    return f"{_ALGORITHM}${_ITERATIONS}${_encode(salt)}${_encode(derived)}"


def verify_passcode(passcode: str, stored: str | None) -> bool:
    """저장된 해시와 맞는지 확인한다. 형식이 깨졌거나 값이 없으면 False.

    비교는 secrets.compare_digest 로 한다. 자리별로 빠져나가면 타이밍으로 값이 새어나간다.
    """
    if not stored or not passcode:
        return False
    parts = stored.split("$")
    if len(parts) != 4 or parts[0] != _ALGORITHM:
        return False
    try:
        iterations = int(parts[1])
        salt = _decode(parts[2])
        expected = _decode(parts[3])
    except (ValueError, TypeError):
        return False
    if iterations <= 0 or not salt or not expected:
        return False
    return hmac.compare_digest(_derive(passcode, salt, iterations), expected)
