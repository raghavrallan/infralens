"""Postgres port of infralens-live/scripts/check-access.mjs.

The live script builds a throwaway SQLite file. These cases use the suite
test database and the merged tenancy model. They do not call Azure.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from app.core import auth
from app.core.db import (
    AuditLog,
    AzureConnection,
    LoginSession,
    Organization,
    OrgMembership,
    Project,
    ProjectConnection,
    ProjectMembership,
    SessionLocal,
    Subscription,
    User,
    init_db,
)
from app.platform.connections import connection_profile_key, set_connection, status
from app.platform.secret_box import decrypt, encrypt
from app.tenancy import orgs, projects
from app.tenancy.access import (
    AccessError,
    audit,
    bind_connections,
    bind_subscriptions,
    can,
    connection_secrets,
    merge_duplicate_azure_connections,
    public_azure_connection,
    replace_subscriptions,
    require_project,
    save_azure_connection,
    subscriptions_for_project,
    visible_projects,
)
from app.tenancy.members import add_org_member
from app.tenancy.sessions import create_session, read_session

pytestmark = pytest.mark.integration

# Frozen with Node scryptSync / AES-256-GCM (APP_SECRET=test-secret, fixed IV).
_LIVE_SCRYPT = (
    "0123456789abcdef0123456789abcdef:"
    "78979e375467c9fbb70925ff8ed721c52f5a8f12efddf19f2eecdade6588c77e"
)
_LIVE_CIPHER = "ABEiM0RVZneImaq7.zgzByWfE49X+LhyKH6EZvw==.uN8S4cMjTik="
_HEX32 = re.compile(r"^[a-f0-9]{32}$")


def _guid() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def app_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_SECRET", "test-secret")


def _hex_id() -> str:
    return uuid.uuid4().hex


def _user(username: str) -> str:
    user_id = _hex_id()
    with SessionLocal() as session:
        session.add(
            User(
                id=user_id,
                username=username,
                email=f"{username}@example.com",
                display_name=username,
                password_hash=auth.hash_password("password-a"),
                role="viewer",
                is_active=True,
            )
        )
        session.commit()
    return user_id


def _org(name: str, slug: str, created_by: str) -> str:
    org_id = _hex_id()
    with SessionLocal() as session:
        session.add(
            Organization(
                id=org_id,
                name=name,
                slug=slug,
                created_by=created_by,
            )
        )
        session.commit()
    return org_id


def _membership(org_id: str, user_id: str, role: str) -> None:
    with SessionLocal() as session:
        session.add(
            OrgMembership(
                id=str(uuid.uuid4()),
                org_id=org_id,
                user_id=user_id,
                org_role=role,
            )
        )
        session.commit()


def _project(org_id: str, name: str, slug: str, budget: float | None = 1000) -> str:
    project_id = _hex_id()
    with SessionLocal() as session:
        session.add(
            Project(
                id=project_id,
                org_id=org_id,
                name=name,
                slug=slug,
                repos=[],
                budget_usd=budget,
            )
        )
        session.commit()
    return project_id


def _project_member(project_id: str, user_id: str, role: str) -> None:
    with SessionLocal() as session:
        session.add(
            ProjectMembership(
                id=str(uuid.uuid4()),
                project_id=project_id,
                user_id=user_id,
                project_role=role,
            )
        )
        session.commit()


def _connection(org_id: str, name: str, client_id: str, secret: str, connection_status: str) -> str:
    connection_id = _hex_id()
    with SessionLocal() as session:
        session.add(
            AzureConnection(
                id=connection_id,
                org_id=org_id,
                name=name,
                tenant_id=client_id,
                client_id=client_id,
                secret_cipher=encrypt(secret),
                status=connection_status,
            )
        )
        session.commit()
    return connection_id


def test_live_access_script_cases(require_db: None, app_secret: None) -> None:
    """The check-access.mjs cases, minus the cost-fold fixture owned by Phase 4."""
    init_db()
    suffix = uuid.uuid4().hex[:8]
    user_a = _user(f"a{suffix}")
    user_b = _user(f"b{suffix}")
    org_a = _org("North Client", f"north-{suffix}", user_a)
    org_b = _org("South Client", f"south-{suffix}", user_b)
    _membership(org_a, user_a, "org_owner")
    _membership(org_b, user_b, "member")
    project_a = _project(org_a, "North prod", f"prod-{suffix}")
    project_b = _project(org_b, "South prod", f"prod-{suffix}")
    project_b2 = _project(org_b, "South other", f"other-{suffix}")
    _project_member(project_b, user_b, "operator")

    sub_a = _guid()
    sub_b = _guid()
    connection_a = _connection(org_a, "A", sub_a, "secret-a", "connected")
    connection_b = _connection(org_b, "B", sub_b, "secret-b", "connected")
    replace_subscriptions(org_a, connection_a, [{"id": sub_a, "name": "North sub", "state": "Enabled"}])
    replace_subscriptions(org_b, connection_b, [{"id": sub_b, "name": "South sub", "state": "Enabled"}])
    bind_connections(org_a, project_a, [connection_a])
    bind_connections(org_b, project_b, [connection_b, connection_b])
    bind_connections(org_b, project_b2, [connection_b])
    with pytest.raises(AccessError) as foreign:
        bind_connections(org_b, project_b, [connection_a])
    assert foreign.value.status == 400

    with SessionLocal() as session:
        mapped = session.query(ProjectConnection).filter_by(project_id=project_b).count()
    assert mapped == 1, "duplicate connection on one project was stored"
    second = [item["id"] for item in subscriptions_for_project(project_b2, org_b)]
    assert second == [sub_b], "the same connection could not be mapped to a second project"

    actor_b = {
        "user": {"id": user_b},
        "org": {"id": org_b},
        "membership": {"role": "member"},
    }
    visible = [item["id"] for item in visible_projects(actor_b)]
    assert project_a not in visible
    assert project_b2 not in visible
    assert project_b in visible

    subs = [item["id"] for item in subscriptions_for_project(project_b, org_b)]
    assert sub_a not in subs
    assert sub_b in subs
    assert subscriptions_for_project(project_a, org_b) == []

    with pytest.raises(AccessError) as blocked:
        replace_subscriptions(
            org_a,
            connection_a,
            [{"id": sub_b, "name": "Stolen", "state": "Enabled"}],
        )
    assert blocked.value.status == 409

    assert can("member", "operator", "billing.read") is False
    assert can("member", "viewer", "billing.read") is True
    assert can("member", "project_admin", "connection.manage") is False
    assert can("org_owner", None, "connection.manage") is True

    token = create_session(user_a, org_a)
    session_row = read_session(token)
    assert session_row is not None
    assert session_row["org_id"] == org_a
    assert session_row["user_id"] == user_a

    with SessionLocal() as session:
        stored = session.get(AzureConnection, connection_a)
        assert stored is not None
        assert decrypt(stored.secret_cipher) == "secret-a"

    actor_a = {
        "user": {"id": user_a},
        "org": {"id": org_a},
        "membership": {"role": "org_owner"},
    }
    owner_visible = {item["id"] for item in visible_projects(actor_a)}
    assert project_a in owner_visible
    assert project_b not in owner_visible
    assert project_b2 not in owner_visible


def test_require_project_returns_404_for_other_org(require_db: None, app_secret: None) -> None:
    init_db()
    suffix = uuid.uuid4().hex[:8]
    user_b = _user(f"req{suffix}")
    org_a = _org("Org A", f"orga-{suffix}", user_b)
    org_b = _org("Org B", f"orgb-{suffix}", user_b)
    _membership(org_b, user_b, "org_owner")
    project_a = _project(org_a, "Hidden", f"hidden-{suffix}", budget=None)
    actor_b = {
        "user": {"id": user_b},
        "org": {"id": org_b},
        "membership": {"role": "org_owner"},
    }
    with pytest.raises(AccessError) as exc:
        require_project(actor_b, project_a, "project.read")
    assert exc.value.status == 404


def test_duplicate_client_id_keeps_connected_row(require_db: None, app_secret: None) -> None:
    init_db()
    suffix = uuid.uuid4().hex[:8]
    user_id = _user(f"dup{suffix}")
    org_id = _org("Dup Org", f"dup-{suffix}", user_id)
    client_id = _guid()
    older = _hex_id()
    newer = _hex_id()
    from app.core.db import engine

    with engine.begin() as conn:
        conn.exec_driver_sql("DROP INDEX IF EXISTS azure_connections_client_id")
    try:
        with SessionLocal() as session:
            session.add(
                AzureConnection(
                    id=older,
                    org_id=org_id,
                    name="Keep",
                    tenant_id=client_id,
                    client_id=client_id.upper(),
                    secret_cipher=encrypt("keep-secret"),
                    status="connected",
                    created_at=datetime.now(timezone.utc) - timedelta(days=2),
                )
            )
            session.add(
                AzureConnection(
                    id=newer,
                    org_id=org_id,
                    name="Drop",
                    tenant_id=client_id,
                    client_id=client_id,
                    secret_cipher=encrypt("drop-secret"),
                    status="error",
                    created_at=datetime.now(timezone.utc),
                )
            )
            session.add(
                Subscription(
                    id=str(uuid.uuid4()),
                    org_id=org_id,
                    connection_id=newer,
                    name="Moved",
                    state="Enabled",
                )
            )
            session.add(ProjectConnection(project_id=_hex_id(), connection_id=newer))
            session.commit()
        removed = merge_duplicate_azure_connections()
        assert removed >= 1
        with SessionLocal() as session:
            assert session.get(AzureConnection, older) is not None
            assert session.get(AzureConnection, newer) is None
            moved = session.query(Subscription).filter_by(org_id=org_id).one()
            assert moved.connection_id == older
            assert session.query(ProjectConnection).filter_by(connection_id=newer).count() == 0
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS azure_connections_client_id "
                "ON azure_connections (lower(client_id))"
            )


def test_client_id_unique_ignores_case(require_db: None, app_secret: None) -> None:
    init_db()
    suffix = uuid.uuid4().hex[:8]
    user_id = _user(f"uniq{suffix}")
    org_id = _org("Uniq Org", f"uniq-{suffix}", user_id)
    client_id = f"{uuid.uuid4()}"
    _connection(org_id, "One", client_id, "secret-one", "pending")
    with pytest.raises(IntegrityError):
        _connection(org_id, "Two", client_id.upper(), "secret-two", "pending")


def test_bind_subscriptions_stays_one_project(require_db: None, app_secret: None) -> None:
    init_db()
    suffix = uuid.uuid4().hex[:8]
    user_id = _user(f"sub{suffix}")
    org_id = _org("Sub Org", f"sub-{suffix}", user_id)
    project_a = _project(org_id, "A", f"a-{suffix}", budget=None)
    project_b = _project(org_id, "B", f"b-{suffix}", budget=None)
    sub_id = _guid()
    connection_id = _connection(org_id, "C", _guid(), "secret-c", "connected")
    replace_subscriptions(
        org_id,
        connection_id,
        [{"id": sub_id, "name": "Only", "state": "Enabled"}],
    )
    bind_subscriptions(org_id, project_a, [sub_id])
    with pytest.raises(AccessError) as exc:
        bind_subscriptions(org_id, project_b, [sub_id])
    assert exc.value.status == 409
    bind_connections(org_id, project_a, [connection_id])
    bind_connections(org_id, project_b, [connection_id])
    assert [item["id"] for item in subscriptions_for_project(project_b, org_id)] == [sub_id]


def test_connection_secrets_stay_on_their_org(require_db: None, app_secret: None) -> None:
    init_db()
    suffix = uuid.uuid4().hex[:8]
    user_id = _user(f"sec{suffix}")
    org_a = _org("Secret A", f"seca-{suffix}", user_id)
    org_b = _org("Secret B", f"secb-{suffix}", user_id)
    connection_id = _connection(org_a, "A", str(uuid.uuid4()), "secret-a", "connected")
    loaded = connection_secrets(connection_id, org_a)
    assert loaded["client_secret"] == "secret-a"
    with pytest.raises(AccessError) as exc:
        connection_secrets(connection_id, org_b)
    assert exc.value.status == 404


def test_public_azure_connection_omits_secret(require_db: None, app_secret: None) -> None:
    init_db()
    suffix = uuid.uuid4().hex[:8]
    user_id = _user(f"pub{suffix}")
    org_id = _org("Public Org", f"pub-{suffix}", user_id)
    client_id = str(uuid.uuid4())
    secret = "client-secret-value"
    saved = save_azure_connection(
        org_id=org_id,
        name="Production reader",
        tenant_id=str(uuid.uuid4()),
        client_id=client_id,
        client_secret=secret,
    )
    blob = json.dumps(saved)
    assert secret not in blob
    assert "secret_cipher" not in saved
    assert saved["client_hint"] == client_id[-4:]
    assert saved["status"]
    with SessionLocal() as session:
        row = session.get(AzureConnection, saved["id"])
        assert row is not None
        assert public_azure_connection(row)["client_hint"] == client_id[-4:]
        assert "secret_cipher" not in public_azure_connection(row)


def test_suite_connection_status_masks_secret(require_db: None, app_secret: None) -> None:
    init_db()
    suffix = uuid.uuid4().hex[:8]
    user_id = _user(f"mask{suffix}")
    org_id = _org("Mask Org", f"mask-{suffix}", user_id)
    project_id = _project(org_id, "Mask", f"maskp-{suffix}", budget=None)
    secret = "suite-secret-value"
    set_connection(
        project_id,
        "azure",
        "client_secret",
        {
            "tenant_id": _guid(),
            "client_id": _guid(),
            "client_secret": secret,
            "subscription_id": _guid(),
        },
    )
    public = status(project_id, "azure")
    assert secret not in json.dumps(public)
    assert public["hint"].endswith(secret[-4:])
    assert public["connected"] is True


def test_project_slug_is_unique_per_org_and_budget_is_optional(require_db: None) -> None:
    init_db()
    suffix = uuid.uuid4().hex[:8]
    admin = _user(f"bud{suffix}")
    org_a = orgs.create_org(name=f"Budget A {suffix}", created_by=admin)
    org_b = orgs.create_org(name=f"Budget B {suffix}", created_by=admin)
    first = projects.create_project("Shared Name", org_id=org_a["id"], budget_usd=1000)
    second = projects.create_project("Shared Name", org_id=org_a["id"], budget_usd=None)
    other_org = projects.create_project("Shared Name", org_id=org_b["id"], budget_usd=None)
    assert first["budget_usd"] == 1000
    assert first["slug"]
    assert second["slug"] != first["slug"]
    assert second["budget_usd"] is None
    assert other_org["slug"] == first["slug"]
    loaded = projects.get_project(first["id"])
    assert loaded is not None
    assert loaded["budget_usd"] == 1000
    with SessionLocal() as session:
        session.add(
            Project(
                id=_hex_id(),
                org_id=org_a["id"],
                name="Clash",
                slug=first["slug"],
                repos=[],
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_audit_log_persists_the_live_columns(require_db: None) -> None:
    init_db()
    suffix = uuid.uuid4().hex[:8]
    user_id = _user(f"aud{suffix}")
    org_id = _org("Audit Org", f"aud-{suffix}", user_id)
    project_id = _project(org_id, "Audit", f"audp-{suffix}", budget=None)
    audit(
        org_id=org_id,
        project_id=project_id,
        user_id=user_id,
        action="member.add",
        detail="person@example.com",
    )
    with SessionLocal() as session:
        row = session.query(AuditLog).filter_by(org_id=org_id, action="member.add").one()
        assert row.project_id == project_id
        assert row.user_id == user_id
        assert row.detail == "person@example.com"
        assert row.created_at is not None


def test_session_read_fails_after_expiry(require_db: None) -> None:
    init_db()
    suffix = uuid.uuid4().hex[:8]
    user_id = _user(f"exp{suffix}")
    org_id = _org("Exp Org", f"exp-{suffix}", user_id)
    token = create_session(user_id, org_id)
    with SessionLocal() as session:
        row = session.query(LoginSession).filter_by(user_id=user_id).one()
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()
    assert read_session(token) is None


def test_profile_key_accepts_uuid_and_hex_ids() -> None:
    hex_id = _hex_id()
    as_uuid = str(uuid.UUID(hex_id))
    assert connection_profile_key(hex_id) == hex_id
    assert connection_profile_key(as_uuid) == hex_id
    derived = connection_profile_key("short-id")
    assert _HEX32.fullmatch(derived)
    assert derived != "short-id"


def test_signup_creates_an_org_the_signer_owns(require_db: None) -> None:
    init_db()
    suffix = uuid.uuid4().hex[:8]
    admin = _user(f"own{suffix}")
    other = orgs.create_org(name=f"Other Client {suffix}", created_by=admin)
    created = orgs.signup_organization(
        name="Ada Lovelace",
        org_name=f"Ada Co {suffix}",
        email=f"ada-{suffix}@example.com",
        password="password-a",
    )
    assert created["org_role"] == "org_owner"
    visible = {item["id"] for item in orgs.list_orgs_for_user({"id": created["user_id"], "role": "viewer"})}
    assert created["org_id"] in visible
    assert other["id"] not in visible
    loaded = orgs.get_org(created["org_id"])
    assert loaded is not None
    assert loaded["created_by"] == created["user_id"]
    assert loaded["slug"]
    assert loaded["created_at"]
    assert loaded["updated_at"]
    with pytest.raises(AccessError) as exc:
        orgs.signup_organization(
            name="Ada Lovelace",
            org_name=f"Ada Again {suffix}",
            email=f"ada-{suffix}@example.com",
            password="password-a",
        )
    assert exc.value.status == 409


def test_live_and_suite_password_hashes_verify() -> None:
    suite_hash = auth.hash_password("correct-horse")
    assert auth.verify_password("correct-horse", suite_hash) is True
    assert auth.verify_password("wrong", suite_hash) is False
    assert auth.verify_password("password-a", _LIVE_SCRYPT) is True
    assert auth.verify_password("wrong", _LIVE_SCRYPT) is False
    assert auth.verify_password("x", "not-a-hash") is False


def test_add_org_member_keeps_live_project_role(require_db: None) -> None:
    init_db()
    suffix = uuid.uuid4().hex[:8]
    owner_id = _user(f"mgr{suffix}")
    org_id = _org("Members", f"mem-{suffix}", owner_id)
    _membership(org_id, owner_id, "org_owner")
    project_id = _project(org_id, "Prod", f"memp-{suffix}", budget=None)
    actor = {
        "user": {"id": owner_id},
        "org": {"id": org_id},
        "membership": {"role": "org_owner"},
    }
    added = add_org_member(
        actor,
        name="Op Person",
        email=f"op-{suffix}@example.com",
        password="password-a",
        org_role="member",
        project_id=project_id,
        project_role="operator",
    )
    assert added["org_role"] == "member"
    with SessionLocal() as session:
        membership = session.query(ProjectMembership).filter_by(project_id=project_id).one()
        assert membership.project_role == "operator"
        user = session.get(User, membership.user_id)
        assert user is not None
        assert auth.verify_password("password-a", user.password_hash) is True
    assert can("member", "operator", "billing.read") is False
    with pytest.raises(AccessError) as missing_project:
        add_org_member(
            actor,
            name="No Project",
            email=f"np-{suffix}@example.com",
            password="password-a",
            org_role="member",
            project_id="",
            project_role="",
        )
    assert missing_project.value.status == 400
    with pytest.raises(AccessError) as owner_role:
        add_org_member(
            actor,
            name="Second Owner",
            email=f"own2-{suffix}@example.com",
            password="password-a",
            org_role="org_owner",
            project_id="",
            project_role="",
        )
    assert owner_role.value.status == 400
    member_actor = {
        "user": {"id": added["user_id"]},
        "org": {"id": org_id},
        "membership": {"role": "member"},
    }
    with pytest.raises(AccessError) as forbidden:
        add_org_member(
            member_actor,
            name="Nope",
            email=f"nope-{suffix}@example.com",
            password="password-a",
            org_role="member",
            project_id=project_id,
            project_role="viewer",
        )
    assert forbidden.value.status == 403


def test_default_project_can_still_be_selected(require_db: None) -> None:
    init_db()
    suffix = uuid.uuid4().hex[:8]
    admin = _user(f"def{suffix}")
    org = orgs.create_org(name=f"Default Org {suffix}", created_by=admin)
    created = projects.create_project(
        "Skills workspace",
        org_id=org["id"],
        owner_user_id=admin,
        owner_project_role="developer",
    )
    selected = projects.set_default(created["id"])
    assert selected is not None
    assert selected["is_default"] is True
    assert selected["id"] == created["id"]
    loaded = projects.get_project(created["id"])
    assert loaded is not None
    assert loaded["is_default"] is True


def test_secret_file_is_created_outside_the_repo_when_app_secret_is_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("APP_SECRET", raising=False)
    target = tmp_path / "app-secret"
    monkeypatch.setattr("app.platform.secret_box._secret_file", lambda: target)
    payload = encrypt("secret-a")
    assert decrypt(payload) == "secret-a"
    assert target.exists()
    assert target.stat().st_mode & 0o777 == 0o600
    gitignore = Path(__file__).resolve().parents[3] / ".gitignore"
    assert "data/" in gitignore.read_text(encoding="utf-8")


def test_live_cipher_matches_the_node_vector(app_secret: None) -> None:
    assert decrypt(_LIVE_CIPHER) == "secret-a"
    round_trip = encrypt("secret-a")
    assert decrypt(round_trip) == "secret-a"
    assert round_trip.count(".") == 2
