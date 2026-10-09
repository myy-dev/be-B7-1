import asyncio
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.main import app
from app.models.user import User
from tests.test_auth_api import PAYLOAD
from tests.test_auth_api import signup_db as _signup_db

signup_db = _signup_db

SECRET = "test-only-secret-key-for-login-tests-12345678901234567890"


def test_member_events_distinguish_outcomes(signup_db, monkeypatch):
    events = []
    monkeypatch.setattr(
        "app.services.auth_service.log_event",
        lambda event, **fields: events.append((event, fields)),
    )
    client = TestClient(app)
    signup = client.post("/api/v1/auth/signup", json=PAYLOAD)
    assert signup.status_code == 201
    user_id = str(signup.json()["id"])
    assert events == [
        ("user_signed_up", {"user_id": user_id, "result": "success"})
    ]
    assert client.post("/api/v1/auth/signup", json=PAYLOAD).status_code == 409
    assert len(events) == 1

    for username in (PAYLOAD["username"], "missing_user"):
        response = client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": "wrong-password"},
        )
        assert response.status_code == 401
        assert events[-1] == (
            "user_login_failed",
            {
                "user_id": user_id if username == PAYLOAD["username"] else None,
                "result": "failure",
                "error_code": "INVALID_CREDENTIALS",
                "http_status": 401,
            },
        )

    response = client.post(
        "/api/v1/auth/login",
        json={"username": PAYLOAD["username"], "password": PAYLOAD["password"]},
    )
    assert response.status_code == 200
    assert events[-1] == (
        "user_logged_in", {"user_id": user_id, "result": "success"}
    )
    assert len(events) == 4


@pytest.fixture(autouse=True)
def configure_auth(monkeypatch):
    from app.api.v1.admin_deps import require_admin

    monkeypatch.delitem(app.dependency_overrides, require_admin, raising=False)
    monkeypatch.setenv("JWT_SECRET_KEY", SECRET)
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_login_and_authenticated_chat(signup_db):
    client = TestClient(app)
    # 회원 ID 1을 가정하지 않는지 확인한다.
    client.post("/api/v1/auth/signup", json={**PAYLOAD, "username": "another_user"})
    user = client.post("/api/v1/auth/signup", json=PAYLOAD).json()
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "TEST_USER", "password": PAYLOAD["password"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"access_token", "token_type", "expires_in"}
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 1800
    claims = jwt.decode(body["access_token"], SECRET, algorithms=["HS256"])
    assert claims["sub"] == str(user["id"])
    assert claims["exp"] - claims["iat"] == 1800
    assert (
        client.get(
            "/api/v1/chats", headers={"Authorization": f"Bearer {body['access_token']}"}
        ).status_code
        == 200
    )

    async def check():
        async with signup_db() as session:
            saved = await session.get(User, user["id"])
            assert saved.last_login_at is not None
            assert (await session.get(User, 1)).last_login_at is None

    asyncio.run(check())


@pytest.mark.parametrize(
    "username,password",
    [
        ("missing_user", PAYLOAD["password"]),
        ("test_user", "wrong-password"),
        ("test_user", "password"),
    ],
)
def test_invalid_credentials(signup_db, username, password):
    client = TestClient(app)
    client.post("/api/v1/auth/signup", json=PAYLOAD)
    response = client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert "access_token" not in response.text


@pytest.mark.parametrize(
    "kind",
    [
        "missing",
        "malformed",
        "expired",
        "forged",
        "missing_exp",
        "deleted",
        "invalid_sub",
        "wrong_algorithm",
    ],
)
def test_authenticated_api_rejects_invalid_auth(signup_db, kind):
    claims = {
        "sub": "1",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(minutes=30),
    }
    key = SECRET
    algorithm = "HS256"
    if kind == "expired":
        claims["exp"] = datetime.now(UTC) - timedelta(seconds=1)
    elif kind == "forged":
        key = "different-signing-key-at-least-32-characters"
    elif kind == "missing_exp":
        del claims["exp"]
    elif kind == "invalid_sub":
        claims["sub"] = "-1"
    elif kind == "wrong_algorithm":
        algorithm = "HS384"
    token = jwt.encode(claims, key, algorithm=algorithm)
    if kind == "malformed":
        token = "not-a-token"
    headers = {} if kind == "missing" else {"Authorization": f"Bearer {token}"}
    response = TestClient(app).get("/api/v1/chats", headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    ("secret", "minutes", "field"),
    [
        (None, "30", "jwt_secret_key"),
        ("", "30", "jwt_secret_key"),
        ("short", "30", "jwt_secret_key"),
        (SECRET, "0", "access_token_expire_minutes"),
        (SECRET, "1441", "access_token_expire_minutes"),
        (SECRET, "invalid", "access_token_expire_minutes"),
    ],
)
def test_invalid_auth_configuration_prevents_startup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    secret: str | None,
    minutes: str,
    field: str,
) -> None:
    """잘못된 JWT 설정은 설정 생성과 새 프로세스의 앱 초기화를 막는다."""
    if secret is None:
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    else:
        monkeypatch.setenv("JWT_SECRET_KEY", secret)
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", minutes)
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None, openai_api_key="test-only")
    assert field in {error["loc"][0] for error in caught.value.errors()}

    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    env["OPENAI_API_KEY"] = "test-only"
    env["OPENAI_MODEL"] = "test-model"
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp_path / 'startup.db'}"
    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode != 0
    assert "ValidationError" in result.stderr
    assert field in result.stderr
    assert not (tmp_path / "startup.db").exists()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"username": "abcd"},
        {"username": "abcd", "password": "short"},
        {"username": "abcd", "password": "password", "role": "admin"},
    ],
)
def test_login_validation(signup_db, payload):
    response = TestClient(app).post("/api/v1/auth/login", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_INPUT"


# 로그아웃 검증: 현재 토큰만 폐기하며 다른 로그인과 재로그인은 유지한다.
def test_logout_revokes_only_current_token(signup_db):
    client = TestClient(app)
    client.post("/api/v1/auth/signup", json=PAYLOAD)
    payload = {"username": PAYLOAD["username"], "password": PAYLOAD["password"]}
    first = client.post("/api/v1/auth/login", json=payload).json()["access_token"]
    second = client.post("/api/v1/auth/login", json=payload).json()["access_token"]
    assert first != second
    headers = {"Authorization": f"Bearer {first}"}
    assert client.get("/api/v1/chats", headers=headers).status_code == 200
    response = client.post("/api/v1/auth/logout", headers=headers)
    assert response.status_code == 204
    assert response.content == b""
    # 새 HTTP 클라이언트도 DB에 보관된 폐기 기록을 확인한다.
    other = TestClient(app)
    for path in ["/api/v1/chats", "/api/v1/admin/users"]:
        assert other.get(path, headers=headers).status_code == 401
    assert other.post("/api/v1/auth/logout", headers=headers).status_code == 401
    assert (
        other.get(
            "/api/v1/chats", headers={"Authorization": f"Bearer {second}"}
        ).status_code
        == 200
    )
    third = other.post("/api/v1/auth/login", json=payload).json()["access_token"]
    assert third not in {first, second}
    assert (
        other.get(
            "/api/v1/chats", headers={"Authorization": f"Bearer {third}"}
        ).status_code
        == 200
    )

    async def check_storage():
        from hashlib import sha256

        from sqlalchemy import select

        from app.models.revoked_token import RevokedToken

        async with signup_db() as session:
            records = (await session.scalars(select(RevokedToken))).all()
            assert len(records) == 1
            assert records[0].token_hash == sha256(first.encode()).hexdigest()

    asyncio.run(check_storage())


# 로그아웃 검증: 인증되지 않은 요청은 폐기 기록을 만들지 않는다.
@pytest.mark.parametrize("token", [None, "forged-token"])
def test_logout_requires_authentication(signup_db, token):
    headers = {} if token is None else {"Authorization": f"Bearer {token}"}
    response = TestClient(app).post("/api/v1/auth/logout", headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
