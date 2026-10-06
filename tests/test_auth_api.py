import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base, get_db
from app.core.security import password_hash
from app.main import app
from app.models.user import User
from app.repositories.user_repository import UserRepository

PAYLOAD = {"username": "Test_User", "password": " password ", "name": " 홍길동 "}


@pytest.fixture
def signup_db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'signup.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def initialize():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def override_db():
        async with sessions() as session:
            yield session

    asyncio.run(initialize())
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override_db
    try:
        yield sessions
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        asyncio.run(engine.dispose())


def test_signup_persists_safe_user(signup_db):
    response = TestClient(app).post("/api/v1/auth/signup", json=PAYLOAD)
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "username", "name", "created_at"}
    assert body["username"] == "test_user"
    assert body["name"] == "홍길동"
    assert body["created_at"].endswith("Z")

    async def check_saved():
        async with signup_db() as session:
            user = await session.get(User, body["id"])
            assert user is not None
            assert user.role == "user"
            assert user.last_login_at is None
            assert user.password_hash != PAYLOAD["password"]
            assert password_hash.verify(PAYLOAD["password"], user.password_hash)
            assert not password_hash.verify("password", user.password_hash)

    asyncio.run(check_saved())


def test_duplicate_username_is_case_insensitive(signup_db):
    client = TestClient(app)
    assert client.post("/api/v1/auth/signup", json=PAYLOAD).status_code == 201
    response = client.post(
        "/api/v1/auth/signup", json={**PAYLOAD, "username": "test_USER"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "USERNAME_TAKEN"
    assert response.json()["error"]["request_id"]


@pytest.mark.parametrize(
    "changes",
    [
        {"username": "abc"},
        {"username": "a" * 21},
        {"username": "한글아이디"},
        {"username": "test-user"},
        {"username": "test_user\n"},
        {"username": " test_user "},
        {"password": "a" * 7},
        {"password": "a" * 129},
        {"name": "   "},
        {"name": "가" * 51},
        {"role": "admin"},
        {"password": None},
    ],
)
def test_signup_rejects_invalid_input(signup_db, changes):
    response = TestClient(app).post("/api/v1/auth/signup", json={**PAYLOAD, **changes})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_INPUT"
    assert PAYLOAD["password"] not in response.text

    async def check_empty():
        async with signup_db() as session:
            assert (await session.scalars(select(User))).all() == []

    asyncio.run(check_empty())


@pytest.mark.parametrize(
    "username,password,name",
    [("abcd", "a" * 8, "가"), ("a" * 20, "a" * 128, "가" * 50)],
)
def test_signup_accepts_length_boundaries(signup_db, username, password, name):
    response = TestClient(app).post(
        "/api/v1/auth/signup",
        json={"username": username, "password": password, "name": name},
    )
    assert response.status_code == 201


def test_concurrent_duplicates_rollback_and_allow_next_signup(signup_db, monkeypatch):
    barrier = Barrier(2)
    original = UserRepository.get_by_username

    async def synchronized_lookup(self, username):
        user = await original(self, username)
        if user is None and username == "test_user":
            # 두 요청 모두 사전 조회를 통과하게 해 DB 고유 제약 경로를 검증한다.
            await asyncio.to_thread(barrier.wait, timeout=10)
        return user

    monkeypatch.setattr(UserRepository, "get_by_username", synchronized_lookup)

    def signup():
        return TestClient(app).post("/api/v1/auth/signup", json=PAYLOAD)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: signup(), range(2)))
    assert sorted(result.status_code for result in results) == [201, 409]
    conflict = next(result for result in results if result.status_code == 409)
    assert conflict.json()["error"]["code"] == "USERNAME_TAKEN"
    assert (
        TestClient(app)
        .post("/api/v1/auth/signup", json={**PAYLOAD, "username": "another_user"})
        .status_code
        == 201
    )

    async def check_count():
        async with signup_db() as session:
            assert len((await session.scalars(select(User))).all()) == 2

    asyncio.run(check_count())
