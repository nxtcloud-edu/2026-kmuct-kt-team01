from uuid import uuid4
import asyncio

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
import httpx
import pytest

from backend.app.edits import EditError, EditService, build_edit_router
from backend.tests.role5.fixtures import FixtureRepository, FixtureStorage, seed_photo


@pytest.fixture
def api(tmp_path):
    repo = FixtureRepository(tmp_path / "api_test.sqlite3")
    storage = FixtureStorage(tmp_path / "objects")
    photo, members = seed_photo(repo, storage)
    service = EditService(repo, storage)

    class SessionError(Exception):
        """Role 3 ApiError-shaped domain exception with an app-level handler."""

    def fixture_member(request: Request) -> str:
        # TEST ONLY. Production MUST inject Role 3's signed-cookie dependency.
        member = request.headers.get("X-Fixture-Member")
        if member == "expired":
            raise HTTPException(status_code=401, detail="Session expired", headers={"WWW-Authenticate": "Cookie"})
        if member == "domain-expired":
            raise SessionError()
        if not member:
            raise EditError("SESSION_REQUIRED", "앨범에 먼저 참여해 주세요.", 401)
        return member

    app = FastAPI()
    @app.exception_handler(SessionError)
    async def session_error_handler(request, error):
        return JSONResponse(status_code=401, content={"code": "INVALID_SESSION", "message": "세션이 만료됐습니다."})
    app.include_router(build_edit_router(service, fixture_member))
    class Client:
        def request(self, method, path, **kwargs):
            async def run():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture") as client:
                    return await client.request(method, path, **kwargs)
            return asyncio.run(run())

        def get(self, path, **kwargs):
            return self.request("GET", path, **kwargs)

        def post(self, path, **kwargs):
            return self.request("POST", path, **kwargs)

        def delete(self, path, **kwargs):
            return self.request("DELETE", path, **kwargs)

    yield Client(), photo, members, storage


def headers(member):
    return {"X-Fixture-Member": member}


def test_api_version_approval_and_revoke_contract(api):
    client, photo, members, _ = api
    url = f"/api/photos/{photo.id}/edits"
    response = client.get(url, headers=headers(members[0]))
    assert response.json()["versions"] == []
    response = client.post(url, json={"brightness": 1.2, "saturation": 0.8, "parent_id": None}, headers=headers(members[0]))
    assert response.status_code == 201
    edit = response.json()
    assert edit["provider"] == "fixture"
    assert edit["mode"] == "fixture"
    assert edit["storage_mode"] == "fixture"
    approval_url = f'/api/edits/{edit["id"]}/approve'
    for member in members:
        approved = client.post(approval_url, headers=headers(member))
        assert approved.status_code == 200
    assert approved.json()["is_final"] is True
    revoked = client.delete(approval_url, headers=headers(members[0]))
    assert revoked.status_code == 200
    assert revoked.json()["is_final"] is False
    assert revoked.json()["approval_count"] == 1


@pytest.mark.parametrize("payload", [
    {"brightness": 2, "saturation": 1}, {"brightness": True, "saturation": 1},
    {"brightness": "1", "saturation": 1}, {"brightness": 1, "saturation": -1},
    {"brightness": 1, "saturation": 1, "parent_id": "bad"},
    {"brightness": 1, "saturation": 1, "member_id": "spoofed"},
    {},
])
def test_invalid_payloads_use_common_error_shape(api, payload):
    client, photo, members, _ = api
    result = client.post(f"/api/photos/{photo.id}/edits", json=payload, headers=headers(members[0]))
    assert result.status_code == 422
    assert result.json()["code"] == "INVALID_REQUEST"
    assert isinstance(result.json()["message"], str)
    assert "detail" not in result.json()


def test_session_uuid_permission_and_missing_resources(api):
    client, photo, members, _ = api
    for path, request_headers, status, code in [
        (f"/api/photos/{photo.id}/edits", {}, 401, "SESSION_REQUIRED"),
        (f"/api/photos/{photo.id}/edits", headers(str(uuid4())), 403, "ALBUM_ACCESS_DENIED"),
        ("/api/photos/bad/edits", headers(members[0]), 422, "INVALID_REQUEST"),
        (f"/api/photos/{uuid4()}/edits", headers(members[0]), 404, "PHOTO_NOT_FOUND"),
    ]:
        response = client.get(path, headers=request_headers)
        assert response.status_code == status
        assert response.json()["code"] == code


def test_storage_failures_do_not_leak_internal_error(api):
    client, photo, members, storage = api
    storage.fail_write = True
    response = client.post(f"/api/photos/{photo.id}/edits", headers=headers(members[0]), json={"brightness": 1, "saturation": 1})
    assert response.status_code == 503
    assert response.json()["code"] == "EDIT_SAVE_FAILED"
    assert "fixture disk failure" not in response.text


def test_standard_session_http_error_preserves_status_and_headers(api):
    client, photo, _, _ = api
    response = client.get(f"/api/photos/{photo.id}/edits", headers=headers("expired"))
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Cookie"
    assert response.json()["code"] == "SESSION_REQUIRED"
    assert isinstance(response.json()["message"], str)


def test_shared_backend_domain_error_handler_remains_effective(api):
    client, photo, _, _ = api
    response = client.get(f"/api/photos/{photo.id}/edits", headers=headers("domain-expired"))
    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_SESSION"
