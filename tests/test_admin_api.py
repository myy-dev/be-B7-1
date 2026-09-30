import json

import pytest
from fastapi.testclient import TestClient

from app.api.v1.admin_deps import get_admin_service
from app.main import app
from app.repositories.admin_mock import (
    MockChatLogRepository,
    MockSessionRepository,
    MockUserRepository,
)
from app.repositories.admin_system_log import SystemLogFileRepository
from app.schemas.admin import UserDetail
from app.services.admin_service import AdminService

client = TestClient(app)


def test_admin_route_passes_with_mock_gate():
    assert client.get("/admin/users").status_code == 200


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_list_users_returns_page():
    res = client.get("/admin/users")
    assert res.status_code == 200
    body = res.json()
    assert set(body) >= {"items", "total", "page", "size"}
    assert body["total"] >= 1


def test_list_users_slices_by_page():
    first = client.get("/admin/users", params={"page": 1, "size": 1}).json()
    second = client.get("/admin/users", params={"page": 2, "size": 1}).json()
    assert len(first["items"]) == 1
    assert len(second["items"]) == 1
    assert first["items"][0]["id"] != second["items"][0]["id"]
    assert first["total"] == second["total"] == 2


def test_user_detail_serializes_only_declared_fields():
    detail = client.get("/admin/users/1").json()
    assert set(detail) <= set(UserDetail.model_fields)
    assert "password" not in json.dumps(detail).lower()


def test_get_user_not_found_returns_standard_error():
    res = client.get("/admin/users/9999")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "USER_NOT_FOUND"


def test_list_logs_filters_by_user():
    res = client.get("/admin/logs", params={"user_id": 1})
    assert res.status_code == 200
    assert all(item["user_id"] == 1 for item in res.json()["items"])


def test_sessions_and_detail():
    listing = client.get("/admin/sessions", params={"user_id": 1}).json()
    assert listing["total"] >= 1
    session_id = listing["items"][0]["id"]
    detail = client.get(f"/admin/sessions/{session_id}").json()
    assert detail["id"] == session_id
    assert isinstance(detail["messages"], list)


def test_get_session_not_found():
    res = client.get("/admin/sessions/9999")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "SESSION_NOT_FOUND"


@pytest.fixture
def sample_log_file(tmp_path):
    path = tmp_path / "system.jsonl"
    path.write_text(
        '{"timestamp":"2026-09-30T05:00:00Z","level":"INFO",'
        '"event":"ai_call_started","user_id":7}\n'
        '{"timestamp":"2026-09-30T06:00:00Z","level":"ERROR",'
        '"event":"ai_call_failed","user_id":7}\n'
        '{"timestamp":"2026-09-30T07:00:00Z","level":"INFO",'
        '"event":"db_save_success","user_id":8}\n'
        "not-json-line\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def file_client(sample_log_file):
    app.dependency_overrides[get_admin_service] = lambda: AdminService(
        users=MockUserRepository(),
        chat_logs=MockChatLogRepository(),
        sessions=MockSessionRepository(),
        system_logs=SystemLogFileRepository(str(sample_log_file)),
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_system_logs_read_from_file_with_event_filter(file_client):
    res = file_client.get("/admin/system-logs", params={"event": "ai_call_started"})
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert body["items"][0]["event"] == "ai_call_started"
    assert body["items"][0]["user_id"] == 7
    assert "_ts" not in body["items"][0]


def test_system_logs_sorted_newest_first(file_client):
    body = file_client.get("/admin/system-logs").json()
    events = [item["event"] for item in body["items"]]
    assert events == ["db_save_success", "ai_call_failed", "ai_call_started"]


@pytest.mark.parametrize(
    "invalid_record",
    [
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
    response = file_client.get("/admin/system-logs")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 4
    assert [item["event"] for item in body["items"]] == [
        "request_received",
        "db_save_success",
        "ai_call_failed",
        "ai_call_started",
    ]
    filtered = file_client.get(
        "/admin/system-logs",
        params={"level": "INFO", "start": "2026-09-30T06:30:00Z", "size": 1, "page": 2},
    )
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 2
    assert filtered.json()["items"][0]["event"] == "db_save_success"


def test_system_logs_only_invalid_records_return_empty_page(
    file_client, sample_log_file
):
    sample_log_file.write_text(
        'not-json\n{"level":"INFO"}\n'
        '{"timestamp":"bad","level":"INFO","event":"request_received"}\n',
        encoding="utf-8",
    )
    response = file_client.get("/admin/system-logs")
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "page": 1, "size": 20}


def test_system_logs_full_flow_file_to_api(file_client, sample_log_file):
    """파일에서 API까지 전 구간: 유효 줄만, 최신순, 페이지 합치기, 원본 불변."""
    import hashlib

    before = hashlib.sha256(sample_log_file.read_bytes()).hexdigest()

    all_items = file_client.get("/admin/system-logs", params={"size": 100}).json()
    assert all_items["total"] == 3

    page1 = file_client.get("/admin/system-logs", params={"size": 2, "page": 1}).json()
    page2 = file_client.get("/admin/system-logs", params={"size": 2, "page": 2}).json()
    joined = [item["event"] for item in page1["items"]] + [
        item["event"] for item in page2["items"]
    ]
    assert joined == [item["event"] for item in all_items["items"]]
    assert page1["total"] == page2["total"] == 3

    after = hashlib.sha256(sample_log_file.read_bytes()).hexdigest()
    assert before == after
