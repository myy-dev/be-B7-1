# 로그인 API 구현
import asyncio
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_auth_settings
from app.main import app
from app.models.user import User
from tests.test_auth_api import PAYLOAD
from tests.test_auth_api import signup_db as _signup_db

signup_db = _signup_db

SECRET = "test-only-secret-key-for-login-tests-12345678901234567890"


@pytest.fixture(autouse=True)
def configure_auth(monkeypatch):
    from app.api.v1.admin_deps import require_admin

    monkeypatch.delitem(app.dependency_overrides, require_admin, raising=False)
    monkeypatch.setenv("JWT_SECRET_KEY", SECRET)
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
    get_auth_settings.cache_clear()
    yield
    get_auth_settings.cache_clear()


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
def test_chat_rejects_invalid_auth(signup_db, kind):
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


def test_bad_secret_returns_configuration_error(signup_db, monkeypatch):
    client = TestClient(app)
    client.post("/api/v1/auth/signup", json=PAYLOAD)
    monkeypatch.setenv("JWT_SECRET_KEY", "short")
    get_auth_settings.cache_clear()
    response = client.post(
        "/api/v1/auth/login",
        json={"username": PAYLOAD["username"], "password": PAYLOAD["password"]},
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "AUTH_CONFIGURATION_ERROR"


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
