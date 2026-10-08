"""관리자 조회 API 테스트.

회원·대화·세션은 실제 DB에서 읽는다(격리 SQLite). 시스템 로그만 실제 파일을
읽으므로 파일→API 전 구간까지 확인한다.
"""

import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base, get_db
from app.main import app
from app.models.chat import Chat, ChatLog
from app.models.user import User
from app.schemas.admin import UserDetail


@pytest.fixture
def admin_db(tmp_path):
    """격리 DB에 회원 2명·세션 1개·기록 2건을 심는다."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'admin.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def initialize():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            now = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
            chat_id = uuid4()
            session.add(
                User(
                    id=1,
                    username="user_a",
                    password_hash="test-only",
                    name="사용자A",
                    role="admin",
                    created_at=now,
                    last_login_at=now,
                )
            )
            session.add(
                User(
                    id=2,
                    username="user_b",
                    password_hash="test-only",
                    name="사용자B",
                    role="user",
                    created_at=now,
                    last_login_at=None,
                )
            )
            session.add(Chat(chat_id=chat_id, user_id=1, created_at=now))
            session.add(
                ChatLog(
                    request_id=uuid4(),
                    chat_id=chat_id,
                    question="배포 방법 알려줘",
                    answer="Vercel과 백엔드 배포 경로를 안내합니다.",
                    status="completed",
                    error_code=None,
                    model="test-model",
                    created_at=now,
                    finished_at=now,
                )
            )
            session.add(
                ChatLog(
                    request_id=uuid4(),
                    chat_id=chat_id,
                    question="아까 뭐 물어봤지?",
                    answer=None,
                    status="failed",
                    error_code="AI_TIMEOUT",
                    model="test-model",
                    created_at=now,
                    finished_at=now,
                )
            )
            await session.commit()
            return chat_id

    async def override_db():
        async with sessions() as session:
            yield session

    chat_id = asyncio.run(initialize())
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override_db
    try:
        yield chat_id
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        asyncio.run(engine.dispose())


@pytest.fixture
def db_client(admin_db):
    yield TestClient(app)


def test_admin_route_passes_with_mock_gate(db_client):
    # 인증은 아직 mock 통과(개발용)라, 게이트가 요청을 막지 않는지 확인한다.
    assert db_client.get("/api/v1/admin/users").status_code == 200


def test_health():
    # 앱이 정상 기동해 헬스 응답을 내는지 확인한다.
    assert TestClient(app).get("/health").json() == {"status": "ok"}


def test_list_users_returns_page(db_client):
    # 회원 목록이 공통 페이지 형태(items·total·page·size)로 오는지 확인한다.
    res = db_client.get("/api/v1/admin/users")
    assert res.status_code == 200
    body = res.json()
    assert set(body) >= {"items", "total", "page", "size"}
    assert body["total"] >= 1


def test_list_users_slices_by_page(db_client):
    # 페이지마다 다른 항목이 오고, total은 전체 수로 일정한지 확인한다.
    # (저장소가 실제로 자르는지 — 이전에 mock이 페이지를 무시하던 회귀 방지)
    first = db_client.get("/api/v1/admin/users", params={"page": 1, "size": 1}).json()
    second = db_client.get("/api/v1/admin/users", params={"page": 2, "size": 1}).json()
    assert len(first["items"]) == 1
    assert len(second["items"]) == 1
    assert first["items"][0]["id"] != second["items"][0]["id"]
    assert first["total"] == second["total"] == 2


def test_user_detail_serializes_only_declared_fields(db_client):
    # 응답이 스키마에 선언한 필드만 나가는지(민감 필드 노출 차단) 확인한다.
    detail = db_client.get("/api/v1/admin/users/1").json()
    assert set(detail) <= set(UserDetail.model_fields)
    assert "password" not in json.dumps(detail).lower()


def test_get_user_not_found_returns_standard_error(db_client):
    # 없는 회원은 404와 공통 에러 형식(code·request_id)으로 오는지 확인한다.
    res = db_client.get("/api/v1/admin/users/9999")
    assert res.status_code == 404
    error = res.json()["error"]
    assert error["code"] == "USER_NOT_FOUND"
    assert isinstance(error["request_id"], str) and error["request_id"]


def test_list_logs_filters_by_user(db_client):
    # 대화 기록이 그 회원 소유 세션으로 걸러지는지 확인한다(기록은 chat_id로 묶임).
    res = db_client.get("/api/v1/admin/logs", params={"user_id": 1})
    assert res.status_code == 200
    assert res.json()["total"] == 2
    # 소유 세션이 없는 회원은 0건이다.
    assert (
        db_client.get("/api/v1/admin/logs", params={"user_id": 2}).json()["total"] == 0
    )


def test_logs_return_record_fields(db_client):
    # 대화 기록이 request_id·status·error_code 등 기록 필드로 오는지 확인한다.
    items = db_client.get("/api/v1/admin/logs", params={"user_id": 1}).json()["items"]
    assert items
    expected = {
        "request_id",
        "chat_id",
        "question",
        "answer",
        "status",
        "error_code",
        "created_at",
        "finished_at",
    }
    assert set(items[0]) == expected
    statuses = {item["status"] for item in items}
    assert statuses <= {"pending", "completed", "failed"}


def test_sessions_and_detail(db_client):
    # 사용자 세션 목록 → 세션 상세(그 세션의 대화 포함) 흐름을 확인한다.
    listing = db_client.get("/api/v1/admin/sessions", params={"user_id": 1}).json()
    assert listing["total"] >= 1
    chat_id = listing["items"][0]["chat_id"]
    detail = db_client.get(f"/api/v1/admin/sessions/{chat_id}").json()
    assert detail["chat_id"] == chat_id
    assert isinstance(detail["messages"], list)


def test_get_session_not_found(db_client):
    # 없는 세션은 404와 공통 에러 형식으로 오는지 확인한다.
    res = db_client.get(f"/api/v1/admin/sessions/{uuid4()}")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "SESSION_NOT_FOUND"


@pytest.fixture
def sample_log_file(tmp_path):
    # 정상 3줄(시간 오름차순)과 깨진 1줄을 담은 임시 로그 파일을 만든다.
    # 정렬·필터·건너뛰기 검증의 기준 데이터가 된다.
    path = tmp_path / "system.jsonl"
    path.write_text(
        '{"timestamp":"2026-09-30T05:00:00Z","level":"INFO",'
        '"event":"ai_call_started","user_id":7}\n'
        '{"timestamp":"2026-09-30T06:00:00Z","level":"ERROR",'
        '"event":"ai_call_failed","user_id":7}\n'
        '{"timestamp":"2026-09-30T07:00:00Z","level":"INFO",'
        '"event":"db_save_succeeded","user_id":8}\n'
        "not-json-line\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def file_client(sample_log_file, tmp_path, monkeypatch):
    # 빈 DB + 임시 시스템 로그 파일로 실제 의존성 체인을 그대로 쓴다.
    from app.core.config import get_settings

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'file.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def initialize():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def override_db():
        async with sessions() as session:
            yield session

    asyncio.run(initialize())
    monkeypatch.setitem(app.dependency_overrides, get_db, override_db)
    settings = get_settings()
    monkeypatch.setattr(settings, "system_log_path", str(sample_log_file))
    yield TestClient(app)
    asyncio.run(engine.dispose())


def test_system_logs_read_from_file_with_event_filter(file_client):
    # event로 거른 결과가 파일과 맞는지, 내부 정렬 키(_ts)가 안 나오는지 확인한다.
    res = file_client.get(
        "/api/v1/admin/system-logs", params={"event": "ai_call_started"}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert body["items"][0]["event"] == "ai_call_started"
    assert body["items"][0]["user_id"] == 7
    assert "_ts" not in body["items"][0]


def test_system_logs_sorted_newest_first(file_client):
    # 정렬은 항상 최신순이어야 한다(파일은 시간 오름차순으로 썼음).
    body = file_client.get("/api/v1/admin/system-logs").json()
    events = [item["event"] for item in body["items"]]
    assert events == ["db_save_succeeded", "ai_call_failed", "ai_call_started"]


@pytest.mark.parametrize(
    "invalid_record",
    [
        # 필수 필드(timestamp·level·event) 누락 또는 형식 오류, 자료형 오류, JSON 배열.
        {"level": "INFO", "event": "request_received"},
        {"timestamp": "not-a-date", "level": "INFO", "event": "request_received"},
        {"timestamp": 123, "level": "INFO", "event": "request_received"},
        {"timestamp": "2026-09-30T08:00:00Z", "event": "request_received"},
        {"timestamp": "2026-09-30T08:00:00Z", "level": "INFO"},
        {"timestamp": "2026-09-30T08:00:00Z", "level": [], "event": "request_received"},
        {
            "timestamp": "2026-09-30T08:00:00Z",
            "level": "INFO",
            "event": "request_received",
            "user_id": "not-an-id",
        },
        [],
    ],
)
def test_system_logs_skip_invalid_records(file_client, sample_log_file, invalid_record):
    # 잘못된 줄 뒤에 정상 줄을 붙여, 깨진 줄만 건너뛰고 조회 전체는 계속되는지 확인한다.
    # (한 줄 때문에 500이 나던 회귀 방지)
    with sample_log_file.open("a", encoding="utf-8") as log:
        log.write(json.dumps(invalid_record) + "\n")
        log.write(
            json.dumps(
                {
                    "timestamp": "2026-09-30T09:00:00Z",
                    "level": "INFO",
                    "event": "request_received",
                }
            )
            + "\n"
        )
    response = file_client.get("/api/v1/admin/system-logs")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 4
    assert [item["event"] for item in body["items"]] == [
        "request_received",
        "db_save_succeeded",
        "ai_call_failed",
        "ai_call_started",
    ]
    filtered = file_client.get(
        "/api/v1/admin/system-logs",
        params={"level": "INFO", "start": "2026-09-30T06:30:00Z", "size": 1, "page": 2},
    )
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 2
    assert filtered.json()["items"][0]["event"] == "db_save_succeeded"


def test_system_logs_only_invalid_records_return_empty_page(
    file_client, sample_log_file
):
    # 전부 깨진 줄이어도 오류가 아니라 200과 빈 페이지를 돌려주는지 확인한다.
    sample_log_file.write_text(
        'not-json\n{"level":"INFO"}\n'
        '{"timestamp":"bad","level":"INFO","event":"request_received"}\n',
        encoding="utf-8",
    )
    response = file_client.get("/api/v1/admin/system-logs")
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "page": 1, "size": 20}


def test_system_logs_full_flow_file_to_api(file_client, sample_log_file):
    """파일에서 API까지 전 구간을 한 흐름으로 확인한다."""
    import hashlib

    # 조회 전후 파일 해시를 비교해, 조회가 원본을 바꾸지 않음을 증명한다.
    before = hashlib.sha256(sample_log_file.read_bytes()).hexdigest()

    # 정상 3줄만, 최신순으로 나온다.
    all_items = file_client.get(
        "/api/v1/admin/system-logs", params={"size": 100}
    ).json()
    assert all_items["total"] == 3

    # 페이지를 나눠 받아 이어붙이면 전체 조회와 순서까지 일치한다.
    page1 = file_client.get(
        "/api/v1/admin/system-logs", params={"size": 2, "page": 1}
    ).json()
    page2 = file_client.get(
        "/api/v1/admin/system-logs", params={"size": 2, "page": 2}
    ).json()
    joined = [item["event"] for item in page1["items"]] + [
        item["event"] for item in page2["items"]
    ]
    assert joined == [item["event"] for item in all_items["items"]]
    assert page1["total"] == page2["total"] == 3

    after = hashlib.sha256(sample_log_file.read_bytes()).hexdigest()
    assert before == after


def test_system_logs_naive_period_filter_treated_as_utc(file_client):
    # 타임존 없는 입력은 UTC로 간주한다 — 타임존 있는 입력과 같은 결과가 나오고,
    # naive·aware 비교로 500이 나던 문제가 다시 생기지 않는지 확인한다.
    aware = file_client.get(
        "/api/v1/admin/system-logs", params={"start": "2026-09-30T06:30:00Z"}
    )
    naive = file_client.get(
        "/api/v1/admin/system-logs", params={"start": "2026-09-30T06:30:00"}
    )
    assert naive.status_code == 200
    assert naive.json() == aware.json()
    assert naive.json()["total"] == 1


def test_system_logs_period_filter_converts_offset_to_utc(file_client):
    # 타임존 있는 입력은 UTC로 환산해 비교한다(+09:00 15:30 == 06:30Z).
    response = file_client.get(
        "/api/v1/admin/system-logs", params={"start": "2026-09-30T15:30:00+09:00"}
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1


def test_system_logs_reversed_period_returns_empty_page(file_client):
    # start가 end보다 뒤여도 500이 아니라 빈 페이지로 끝나는지 확인한다.
    response = file_client.get(
        "/api/v1/admin/system-logs",
        params={"start": "2026-09-30T07:00:00", "end": "2026-09-30T06:00:00"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0


def test_validation_error_uses_common_error_shape(db_client):
    # 422도 FastAPI 기본 형식(detail)이 아니라 공통 오류 형식으로 나가는지 확인한다.
    # (프론트가 error.message로 사용자 문구를 꺼내는 계약)
    res = db_client.get("/api/v1/admin/users", params={"page": 0})
    assert res.status_code == 422
    error = res.json()["error"]
    assert error["code"] == "INVALID_INPUT"
    assert isinstance(error["message"], str) and error["message"]
    assert isinstance(error["request_id"], str) and error["request_id"]
    assert "detail" not in res.json()


def test_admin_paths_use_api_v1_prefix(db_client):
    # 관리자 경로가 /api/v1 접두어 아래에 있고, 접두어 없는 구 경로는 404인지 확인한다.
    assert db_client.get("/api/v1/admin/users").status_code == 200
    assert db_client.get("/admin/users").status_code == 404


def test_cors_allows_configured_origin(db_client):
    # 허용된 프론트 오리진에는 CORS 응답 헤더가 붙는지 확인한다.
    res = db_client.get(
        "/api/v1/admin/users", headers={"Origin": "http://localhost:5173"}
    )
    assert res.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_preflight_allows_authorization_header(db_client):
    # 프리플라이트가 Authorization 헤더를 허용해 실연결 시 막히지 않는지 확인한다.
    res = db_client.options(
        "/api/v1/admin/users",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") == "http://localhost:5173"
    allowed = res.headers.get("access-control-allow-headers", "")
    assert "authorization" in allowed.lower()


def test_cors_blocks_unconfigured_origin(db_client):
    # 허용 목록에 없는 오리진에는 allow-origin 헤더를 주지 않는지 확인한다.
    res = db_client.get(
        "/api/v1/admin/users", headers={"Origin": "http://evil.example"}
    )
    assert "access-control-allow-origin" not in res.headers


def test_unknown_path_uses_common_error_shape(db_client):
    # 없는 경로(라우터 밖)의 404도 공통 오류 형식으로 나가는지 확인한다.
    res = db_client.get("/api/v1/nope")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "NOT_FOUND"


def test_cors_config_loads_comma_separated_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """문서에 정의된 쉼표 구분 CORS 환경변수를 정상적으로 읽는다.

    Args:
        monkeypatch: 테스트용 CORS 환경변수와 API 키를 설정할 도구.
    """
    from app.core.config import Settings

    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173, http://127.0.0.1:5173, ")
    settings = Settings(_env_file=None)
    assert settings.cors_origins == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
