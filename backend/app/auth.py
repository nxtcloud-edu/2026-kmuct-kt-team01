from __future__ import annotations

from itsdangerous import BadSignature, URLSafeSerializer

from backend.app.errors import ApiError


class SessionCodec:
    def __init__(self, secret: str) -> None:
        self._serializer = URLSafeSerializer(secret, salt="zzik-member-session-v1")

    def encode(self, member_id: str) -> str:
        return self._serializer.dumps({"member_id": member_id})

    def decode(self, value: str | None) -> str:
        if not value:
            raise ApiError(401, "SESSION_REQUIRED", "앨범 참여가 필요합니다.")
        try:
            payload = self._serializer.loads(value)
        except BadSignature as exc:
            raise ApiError(401, "INVALID_SESSION", "세션이 유효하지 않습니다.") from exc
        member_id = payload.get("member_id") if isinstance(payload, dict) else None
        if not isinstance(member_id, str):
            raise ApiError(401, "INVALID_SESSION", "세션이 유효하지 않습니다.")
        return member_id
