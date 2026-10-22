"""The per-friend invite gate (M11.1)."""
import pytest
from sqlalchemy import select

from app.api import access as access_api
from app.config import get_settings
from app.models.invite import InviteCode
from app.models.user import User
from app.services import invites

GAME = '[White "A"]\n[Black "B"]\n[Result "*"]\n\n1. e4 e5 *\n'


@pytest.fixture
def private(monkeypatch):
    monkeypatch.setattr(get_settings(), "access_required", True)
    access_api.ATTEMPTS.clear()
    yield
    access_api.ATTEMPTS.clear()


def new_invite(db_factory, label="Alice"):
    with db_factory() as db:
        invite, code = invites.create(db, label)
        return invite.id, code


def test_an_open_server_needs_no_code(client):
    body = client.get("/api/access").json()
    assert body == {"required": False, "unlocked": True, "label": None}
    assert client.get("/api/games").status_code == 200


def test_a_private_server_refuses_everything_until_unlocked(client, db_factory, private):
    assert client.get("/api/access").json() == {"required": True, "unlocked": False, "label": None}
    assert client.get("/api/games").status_code == 403
    assert client.post("/api/imports/pgn", json={"pgn_text": GAME}).status_code == 403
    assert client.get("/api/settings").status_code == 403
    assert client.post("/api/session").status_code == 200  # starting a session is still allowed

    _, code = new_invite(db_factory)
    r = client.post("/api/access", json={"code": code})
    assert r.status_code == 200 and r.json() == {"required": True, "unlocked": True, "label": "Alice"}
    assert client.get("/api/games").status_code == 200
    assert client.post("/api/imports/pgn", json={"pgn_text": GAME}).status_code == 200


def test_wrong_codes_are_refused_without_saying_why(client, db_factory, private):
    new_invite(db_factory)
    a = client.post("/api/access", json={"code": "nope"})
    assert a.status_code == 403 and a.json()["detail"] == "That code is not valid."
    assert client.get("/api/games").status_code == 403
    assert client.post("/api/access", json={"code": ""}).status_code == 422


def test_codes_are_stored_only_as_hashes(db_factory):
    _, code = new_invite(db_factory)
    with db_factory() as db:
        invite = db.scalar(select(InviteCode))
        assert code not in (invite.code_hash, invite.label) and len(invite.code_hash) == 64


def test_revoking_cuts_off_every_browser_that_used_it(client, make_client, db_factory, private):
    invite_id, code = new_invite(db_factory)
    other = make_client()
    for c in (client, other):
        assert c.post("/api/access", json={"code": code}).status_code == 200
        assert c.get("/api/games").status_code == 200
    with db_factory() as db:
        assert invites.revoke(db, invite_id)
    for c in (client, other):
        assert c.get("/api/games").status_code == 403
        assert c.get("/api/access").json()["unlocked"] is False
    # a revoked code cannot be used again
    assert make_client().post("/api/access", json={"code": code}).status_code == 403


def test_each_friend_has_their_own_code(client, make_client, db_factory, private):
    _, a = new_invite(db_factory, "Alice")
    _, b = new_invite(db_factory, "Bob")
    other = make_client()
    client.post("/api/access", json={"code": a})
    other.post("/api/access", json={"code": b})
    assert client.get("/api/access").json()["label"] == "Alice"
    assert other.get("/api/access").json()["label"] == "Bob"
    with db_factory() as db:
        assert len({u.invite_id for u in db.scalars(select(User)) if u.invite_id}) == 2


def test_guessing_is_rate_limited(client, db_factory, private):
    new_invite(db_factory)
    codes = [client.post("/api/access", json={"code": f"guess{i}"}).status_code for i in range(12)]
    assert codes[:10] == [403] * 10
    assert codes[10:] == [429, 429]
    # even the right code is refused while limited
    with db_factory() as db:
        _, good = invites.create(db, "Late")
    assert client.post("/api/access", json={"code": good}).status_code == 429


def test_health_check_stays_open(client, private):
    assert client.get("/api/healthz").status_code == 200
