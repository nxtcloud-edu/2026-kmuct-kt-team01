from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from backend.app.analysis import AnalysisError
from backend.app.models import Member, Photo, PhotoMember
from backend.app.worker import process_one
from tests.test_api import create_album, jpeg_bytes, make_client


def test_worker_preserves_manual_links_and_marks_mock_mode(tmp_path, monkeypatch) -> None:
    client, app = make_client(tmp_path)
    album = create_album(client)
    photo_id = client.post(
        f"/api/albums/{album['album_id']}/photos",
        files=[("files", ("one.jpg", jpeg_bytes(), "image/jpeg"))],
    ).json()["results"][0]["photo"]["id"]
    with app.state.session_factory() as db:
        member = db.scalar(select(Member).where(Member.album_id == album["album_id"]))
        db.add(
            PhotoMember(
                photo_id=photo_id,
                member_id=member.id,
                source="manual",
                excluded=True,
            )
        )
        db.commit()
        member_id = member.id

    monkeypatch.setattr(
        "backend.app.worker.analyze",
        lambda *_: {
            "faces": [
                {"member_id": member_id, "similarity": 99.0, "status": "matched"},
                {"status": "uncertain"},
                {"status": "unregistered"},
            ],
            "face_count": 3,
            "shot_type": "group",
            "tags": ["person"],
            "quality": {"sharpness": 80.0},
            "best_score": 80.0,
            "provider": "contract-fixture",
            "mode": "mock",
            "capture": {"captured_at": None},
        },
    )
    assert process_one(app.state.session_factory, app.state.storage) is True

    with app.state.session_factory() as db:
        photo = db.get(Photo, photo_id)
        links = list(db.scalars(select(PhotoMember).where(PhotoMember.photo_id == photo_id)))
        assert photo.analysis_status == "done"
        assert (photo.provider, photo.mode) == ("contract-fixture", "mock")
        assert (photo.uncertain_face_count, photo.unregistered_face_count) == (1, 1)
        assert [(link.member_id, link.source, link.excluded) for link in links] == [
            (member_id, "manual", True)
        ]


def test_worker_groups_only_photos_with_capture_time(tmp_path, monkeypatch) -> None:
    client, app = make_client(tmp_path)
    album = create_album(client)
    upload = client.post(
        f"/api/albums/{album['album_id']}/photos",
        files=[
            ("files", ("a.jpg", jpeg_bytes(), "image/jpeg")),
            ("files", ("b.jpg", jpeg_bytes(), "image/jpeg")),
        ],
    ).json()
    ids = [result["photo"]["id"] for result in upload["results"]]
    now = datetime.now(timezone.utc)
    with app.state.session_factory() as db:
        db.get(Photo, ids[0]).captured_at = now
        db.get(Photo, ids[1]).captured_at = now + timedelta(seconds=2)
        db.commit()

    results = iter(
        [
            (70.0, now.isoformat()),
            (90.0, (now + timedelta(seconds=2)).isoformat()),
        ]
    )

    def fake_analyze(*_):
        score, captured_at = next(results)
        return {
            "faces": [],
            "face_count": 2,
            "shot_type": "group",
            "tags": [],
            "quality": {},
            "best_score": score,
            "provider": "contract-fixture",
            "mode": "mock",
            "capture": {"captured_at": captured_at},
        }

    monkeypatch.setattr("backend.app.worker.analyze", fake_analyze)
    assert process_one(app.state.session_factory, app.state.storage) is True
    assert process_one(app.state.session_factory, app.state.storage) is True
    with app.state.session_factory() as db:
        photos = [db.get(Photo, photo_id) for photo_id in ids]
        assert photos[0].burst_group_id == photos[1].burst_group_id
        assert photos[0].burst_group_id is not None
        assert [photo.is_best for photo in photos] == [False, True]


def test_real_mock_analysis_runs_through_api_storage_and_worker(tmp_path) -> None:
    client, app = make_client(tmp_path)
    album = create_album(client)
    reference = client.post(
        "/api/members/me/reference",
        files={"file": ("selfie.jpg", jpeg_bytes(), "image/jpeg")},
    )
    assert reference.status_code == 200

    uploaded = client.post(
        f"/api/albums/{album['album_id']}/photos",
        files=[("files", ("trip.jpg", jpeg_bytes(), "image/jpeg"))],
    ).json()
    photo_id = uploaded["results"][0]["photo"]["id"]
    assert process_one(app.state.session_factory, app.state.storage) is True

    detail = client.get(f"/api/photos/{photo_id}")
    assert detail.status_code == 200
    assert detail.json()["analysis_status"] == "done"
    assert detail.json()["provider"] == "mock"
    assert detail.json()["mode"] == "mock"
    assert detail.json()["is_best"] is True
    status = client.get(f"/api/albums/{album['album_id']}/status").json()
    assert status == {"pending": 0, "processing": 0, "done": 1, "failed": 0}


def test_worker_retries_only_retryable_errors_and_stores_final_code(tmp_path, monkeypatch) -> None:
    client, app = make_client(tmp_path)
    album = create_album(client)
    client.post(
        f"/api/albums/{album['album_id']}/photos",
        files=[("files", ("retry.jpg", jpeg_bytes(), "image/jpeg"))],
    )
    attempts = 0

    def unavailable(*_):
        nonlocal attempts
        attempts += 1
        raise AnalysisError("AWS_UNAVAILABLE", "temporary detail", retryable=True)

    monkeypatch.setattr("backend.app.worker.analyze", unavailable)
    monkeypatch.setattr("backend.app.worker.time.sleep", lambda _: None)
    assert process_one(app.state.session_factory, app.state.storage) is True
    with app.state.session_factory() as db:
        photo = db.scalar(select(Photo).where(Photo.album_id == album["album_id"]))
        assert attempts == 3
        assert photo.analysis_status == "failed"
        assert photo.analysis_error == "AWS_UNAVAILABLE"
