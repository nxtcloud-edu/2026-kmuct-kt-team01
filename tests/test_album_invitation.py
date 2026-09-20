from fastapi.testclient import TestClient

from tests.test_api import make_client


def test_mixed_case_invitation_joins_same_album_with_independent_session(tmp_path, monkeypatch):
    monkeypatch.setattr('backend.app.api.secrets.token_urlsafe', lambda _: 'aB9_xY-2zQ1')
    owner, app = make_client(tmp_path)
    try:
        with owner, TestClient(app) as guest:
            created = owner.post('/api/albums', json={'name': 'Trip', 'display_name': 'Owner', 'passcode': 'owner-pass'})
            assert created.status_code == 201
            album = created.json()
            assert album['invite_code'] == 'aB9_xY-2zQ1'
            assert guest.get(f"/api/albums/{album['album_id']}").status_code == 401
            joined = guest.post('/api/albums/join', json={'invite_code': album['invite_code'], 'display_name': 'Guest', 'passcode': 'guest-pass'})
            assert joined.status_code == 200
            assert joined.json()['album_id'] == album['album_id']
            assert joined.json()['member_id'] != album['member_id']
            assert guest.cookies.get('zzik_session') != owner.cookies.get('zzik_session')
            for client in (owner, guest):
                detail = client.get(f"/api/albums/{album['album_id']}")
                assert detail.status_code == 200
                assert detail.json()['invite_code'] == album['invite_code']
                assert {member['display_name'] for member in detail.json()['members']} == {'Owner', 'Guest'}
    finally:
        app.state.engine.dispose()
