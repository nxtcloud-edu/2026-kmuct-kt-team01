"""Run explicitly on the assembled backend, never against a demo/production DB.

python -m pytest docs/assembly/checks/role5_acceptance.py -q
All clients use a temporary SQLite _test DB and LocalStorage; analysis is fixture.
"""
import hashlib
import io
import zipfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.models import Base, Photo, PhotoMember


@pytest.fixture
def session(tmp_path):
    app = create_app(Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'role5_acceptance_test.sqlite'}",
        session_secret="role5-local-acceptance-only",
        local_storage_path=tmp_path / "objects",
    ))
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as owner, TestClient(app) as guest:
        album = owner.post('/api/albums', json={'name': 'fixture', 'display_name': 'owner'}).json()
        joined = guest.post('/api/albums/join', json={
            'invite_code': album['invite_code'], 'display_name': 'guest'}).json()
        yield app, owner, guest, album, joined
    app.state.engine.dispose()


def upload(session):
    app, owner, _, album, _ = session
    output = io.BytesIO()
    with Image.new('RGB', (32, 24), '#7c3aed') as image:
        image.save(output, format='PNG')
    raw = output.getvalue()
    response = owner.post(f"/api/albums/{album['album_id']}/photos",
                          files=[('files', ('fixture.png', raw, 'image/png'))])
    assert response.status_code == 200
    item = response.json()['results'][0]
    assert item['ok']
    return item['photo']['id'], raw


def mark_analyzed(session, photo_id, *, confirmed=False, shot_type='no_face'):
    app, _, _, album, joined = session
    with app.state.session_factory() as db:
        photo = db.get(Photo, photo_id)
        photo.analysis_status = 'done'
        photo.face_count = 0 if shot_type == 'no_face' else 2
        photo.shot_type = shot_type
        photo.provider = 'contract-fixture'
        photo.mode = 'mock'
        if confirmed:
            for member_id in (album['member_id'], joined['member_id']):
                db.add(PhotoMember(photo_id=photo_id, member_id=member_id, source='manual', excluded=False))
        db.commit()


def save(owner, photo_id, brightness):
    response = owner.post(f'/api/photos/{photo_id}/edits', json={'brightness': brightness, 'saturation': 1})
    assert response.status_code == 201
    return response.json()['id']


def download_final(session, photo_id):
    _, owner, _, album, _ = session
    return owner.post(f"/api/albums/{album['album_id']}/download",
                      json={'photo_ids': [photo_id], 'version': 'final'})


def test_uploaded_png_is_downloaded_byte_for_byte(session):
    app, owner, _, _, _ = session
    photo_id, raw = upload(session)
    response = owner.get(f'/api/photos/{photo_id}/download')
    assert response.status_code == 200
    assert response.content == raw, 'Original download must preserve uploaded PNG bytes'
    with app.state.session_factory() as db:
        photo = db.get(Photo, photo_id)
        assert photo.content_hash == hashlib.sha256(response.content).hexdigest()


def test_no_face_override_agrees_between_approval_and_final_zip(session):
    _, owner, _, album, _ = session
    photo_id, _ = upload(session)
    # Manual links can remain even when the analysis says no_face.
    mark_analyzed(session, photo_id, confirmed=True)
    edit_id = save(owner, photo_id, 1.1)
    approved = owner.post(f'/api/edits/{edit_id}/approve').json()
    assert approved['required_member_ids'] == [album['member_id']]
    assert approved['is_final']
    response = download_final(session, photo_id)
    assert response.status_code == 200, response.text


def test_two_sessions_revoke_fallback_and_restart_preserve_version(session):
    app, owner, guest, _, _ = session
    photo_id, _ = upload(session)
    mark_analyzed(session, photo_id, confirmed=True, shot_type='group')
    first = save(owner, photo_id, 0.8)
    second = save(owner, photo_id, 1.2)
    for edit_id in (first, second):
        assert not owner.post(f'/api/edits/{edit_id}/approve').json()['is_final']
        assert guest.post(f'/api/edits/{edit_id}/approve').json()['is_final']
    assert guest.delete(f'/api/edits/{second}/approve').status_code == 200
    assert owner.get(f'/api/photos/{photo_id}/edits').json()['final_edit_id'] == first
    response = download_final(session, photo_id)
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist() == ['fixture-edit-1.jpg']
        saved = archive.read(archive.namelist()[0])
    # Rebuild the app from the same test database/storage and reuse the signed session.
    restarted = create_app(app.state.settings)
    try:
        with TestClient(restarted) as client:
            client.cookies.update(owner.cookies)
            assert client.get(f'/api/photos/{photo_id}/edits').json()['final_edit_id'] == first
            album_id = session[3]['album_id']
            response = client.post(f'/api/albums/{album_id}/download', json={'photo_ids': [photo_id], 'version': 'final'})
            assert response.status_code == 200
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                assert archive.read(archive.namelist()[0]) == saved
    finally:
        restarted.state.engine.dispose()


def test_worker_preserves_manual_exclusion_made_during_analysis(session, monkeypatch):
    from backend.app.worker import process_one

    app, owner, _, album, _ = session
    photo_id, _ = upload(session)
    member_id = album['member_id']
    with app.state.session_factory() as db:
        db.add(PhotoMember(photo_id=photo_id, member_id=member_id,
                           source='auto', excluded=False))
        db.commit()

    def analysis_with_concurrent_manual_change(*_):
        # process_one has already loaded member_links when this callback runs.
        response = owner.put(f'/api/photos/{photo_id}/members', json={
            'members': [{'member_id': member_id, 'excluded': True}],
        })
        assert response.status_code == 200, response.text
        return {
            'faces': [{'status': 'matched', 'member_id': member_id, 'similarity': 99}],
            'face_count': 1, 'shot_type': 'solo', 'tags': [], 'quality': {},
            'provider': 'contract-fixture', 'mode': 'mock',
        }

    monkeypatch.setattr('backend.app.worker.run_analysis_with_retries',
                        analysis_with_concurrent_manual_change)
    assert process_one(app.state.session_factory, app.state.storage)
    with app.state.session_factory() as db:
        photo = db.get(Photo, photo_id)
        link = db.get(PhotoMember, (photo_id, member_id))
        assert (link.source, link.excluded) == ('manual', True)
        assert photo.analysis_status == 'done', (
            'A manual exclusion during analysis must survive without failing the worker; '
            f'got {photo.analysis_status}: {photo.analysis_error}'
        )
