from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

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
            "faces": [{"member_id": member_id, "similarity": 99.0}],
            "face_count": 1,
            "shot_type": "solo",
            "tags": ["person"],
            "quality": {"sharpness": 80.0},
            "best_score": 80.0,
            "provider": "contract-fixture",
            "mode": "mock",
        },
    )
    assert process_one(app.state.session_factory, app.state.storage) is True

    with app.state.session_factory() as db:
        photo = db.get(Photo, photo_id)
        links = list(db.scalars(select(PhotoMember).where(PhotoMember.photo_id == photo_id)))
        assert photo.analysis_status == "done"
        assert (photo.provider, photo.mode) == ("contract-fixture", "mock")
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

    scores = iter([70.0, 90.0])

    def fake_analyze(*_):
        score = next(scores)
        return {
            "faces": [],
            "face_count": 2,
            "shot_type": "group",
            "tags": [],
            "quality": {},
            "best_score": score,
            "provider": "contract-fixture",
            "mode": "mock",
        }

    monkeypatch.setattr("backend.app.worker.analyze", fake_analyze)
    assert process_one(app.state.session_factory, app.state.storage) is True
    assert process_one(app.state.session_factory, app.state.storage) is True
    with app.state.session_factory() as db:
        photos = [db.get(Photo, photo_id) for photo_id in ids]
        assert photos[0].burst_group_id == photos[1].burst_group_id
        assert photos[0].burst_group_id is not None
        assert [photo.is_best for photo in photos] == [False, True]
