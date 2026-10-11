import asyncio
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.user import User
from tests.test_auth_api import PAYLOAD
from tests.test_auth_api import signup_db as _signup_db
from tests.test_login_api import SECRET
from tests.test_login_api import configure_auth as _configure_auth

signup_db = _signup_db
configure_auth = _configure_auth
PATH = "/api/v1/auth/me"


def login(client, username):
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": PAYLOAD["password"]},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_my_info_returns_only_authenticated_users_safe_fields(signup_db):
    client = TestClient(app)
    first = client.post("/api/v1/auth/signup", json=PAYLOAD).json()
    second = client.post(
        "/api/v1/auth/signup",
        json={**PAYLOAD, "username": "another_user", "name": "다른 회원"},
    ).json()
    for user in [first, second]:
        headers = login(client, user["username"])
        response = client.get(PATH, headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {
            "id",
            "username",
            "name",
            "role",
            "created_at",
            "last_login_at",
        }
        assert body == {**user, "role": "user", "last_login_at": body["last_login_at"]}
        assert body["created_at"].endswith("Z")
        assert body["last_login_at"].endswith("Z")
        assert PAYLOAD["password"] not in response.text


@pytest.mark.parametrize(
    "kind", ["missing", "malformed", "expired", "forged", "deleted", "revoked"]
)
def test_my_info_rejects_invalid_auth(signup_db, kind):
    client = TestClient(app)
    user = client.post("/api/v1/auth/signup", json=PAYLOAD).json()
    headers = login(client, user["username"])
    if kind == "missing":
        headers = {}
    elif kind == "malformed":
        headers = {"Authorization": "Bearer invalid-token"}
    elif kind in {"expired", "forged"}:
        claims = {
            "sub": str(user["id"]),
            "iat": datetime.now(UTC) - timedelta(minutes=1),
            "exp": datetime.now(UTC) + timedelta(minutes=30),
        }
        if kind == "expired":
            claims["exp"] = datetime.now(UTC) - timedelta(seconds=1)
        key = (
            SECRET
            if kind == "expired"
            else "different-signing-key-at-least-32-characters"
        )
        token = jwt.encode(claims, key, algorithm="HS256")
        headers = {"Authorization": f"Bearer {token}"}
    elif kind == "deleted":

        async def delete_user():
            async with signup_db() as session:
                await session.delete(await session.get(User, user["id"]))
                await session.commit()

        asyncio.run(delete_user())
    elif kind == "revoked":
        assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    response = client.get(PATH, headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_my_info_supports_null_last_login_and_current_db_values(signup_db):
    client = TestClient(app)
    user = client.post("/api/v1/auth/signup", json=PAYLOAD).json()
    headers = login(client, user["username"])

    async def update_user():
        async with signup_db() as session:
            saved = await session.get(User, user["id"])
            saved.name = "변경한 이름"
            saved.role = "admin"
            saved.last_login_at = None
            await session.commit()

    asyncio.run(update_user())
    response = client.get(PATH, headers=headers)
    assert response.status_code == 200
    assert response.json()["name"] == "변경한 이름"
    assert response.json()["role"] == "admin"
    assert response.json()["last_login_at"] is None


def test_my_info_openapi_requires_bearer_auth():
    operation = TestClient(app).get("/openapi.json").json()["paths"][PATH]["get"]
    assert operation["security"] == [{"HTTPBearer": []}]
    assert "requestBody" not in operation
    assert "401" in operation["responses"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/MyInfoResponse"
    }
