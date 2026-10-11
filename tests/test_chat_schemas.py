"""채팅 API 명세의 응답 구조와 상태별 데이터 규칙을 검증한다."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from app.schemas.chat import (
    ChatDetailResponse,
    ChatListResponse,
    ChatResponse,
    MessageCreateRequest,
    MessageResponse,
)
from app.schemas.error import ErrorResponse


def _response_examples() -> list[tuple[type[BaseModel], dict[str, object]]]:
    api_path = Path(__file__).resolve().parents[1] / "docs/PRD/chat-spec.md"
    examples = re.findall(r"```json\n(.*?)\n```", api_path.read_text(), re.S)
    responses: list[tuple[type[BaseModel], dict[str, object]]] = []
    for example in examples:
        data = json.loads(example)
        if "question" in data and "request_id" not in data:
            continue
        schema: type[BaseModel]
        if "error" in data:
            schema = ErrorResponse
        elif "items" in data:
            schema = ChatListResponse
        elif "messages" in data:
            schema = ChatDetailResponse
        elif "request_id" in data:
            schema = MessageResponse
        else:
            schema = ChatResponse
        responses.append((schema, data))
    return responses


def test_api_contains_five_response_examples() -> None:
    """명세서의 응답 예제 5개가 모두 검증 대상인지 확인한다."""
    assert len(_response_examples()) == 5


@pytest.mark.parametrize(
    ("schema", "data"),
    _response_examples(),
    ids=lambda value: value.__name__ if isinstance(value, type) else None,
)
def test_api_response_examples_round_trip(
    schema: type[BaseModel], data: dict[str, object]
) -> None:
    """명세서의 응답 예제가 필드·값 변경 없이 직렬화되는지 확인한다."""
    assert schema.model_validate(data).model_dump(mode="json") == data


def _pending_record() -> dict[str, object]:
    return {
        "request_id": str(uuid4()),
        "chat_id": str(uuid4()),
        "question": "질문",
        "answer": None,
        "status": "pending",
        "error_code": None,
        "created_at": "2026-10-03T07:00:00Z",
        "finished_at": None,
    }


def test_pending_and_failed_keep_null_fields() -> None:
    """처리 중·실패 기록이 명세의 null 필드를 모두 반환하는지 확인한다."""
    data = _pending_record()
    pending = MessageResponse.model_validate(data).model_dump(mode="json")
    assert set(pending) == set(data)
    for field in ("answer", "error_code", "finished_at"):
        assert pending[field] is None

    data.update(
        status="failed",
        error_code="AI_TIMEOUT",
        finished_at="2026-10-03T07:00:30Z",
    )
    failed = MessageResponse.model_validate(data).model_dump(mode="json")
    assert failed["answer"] is None
    assert failed["error_code"] == "AI_TIMEOUT"
    assert failed["finished_at"] == "2026-10-03T07:00:30Z"


@pytest.mark.parametrize(
    "changes",
    [
        {"answer": "아직 완료되지 않은 답변"},
        {"status": "completed"},
        {"status": "failed"},
    ],
    ids=["pending-with-answer", "completed-without-result", "failed-without-result"],
)
def test_inconsistent_status_is_rejected(changes: dict[str, object]) -> None:
    """상태와 결과 필드가 모순인 기록이 거절되는지 확인한다."""
    with pytest.raises(ValidationError):
        MessageResponse.model_validate(_pending_record() | changes)


def test_empty_collections() -> None:
    """채팅방과 대화 기록이 없을 때 빈 배열을 유지하는지 확인한다."""
    assert ChatListResponse(items=[]).model_dump() == {"items": []}
    detail = ChatDetailResponse(
        chat_id=uuid4(), created_at=datetime.now(UTC), messages=[]
    )
    assert detail.model_dump(mode="json")["messages"] == []


def test_timestamps_are_normalized_to_utc() -> None:
    """시간대가 있는 시각은 UTC로 변환하고 시간대 없는 값은 거절한다."""
    chat_id = uuid4()
    response = ChatResponse(
        chat_id=chat_id, created_at="2026-10-03T16:00:00+09:00"
    )
    assert response.model_dump(mode="json")["created_at"] == "2026-10-03T07:00:00Z"
    with pytest.raises(ValidationError):
        ChatResponse(chat_id=chat_id, created_at="2026-10-03T07:00:00")


def test_question_is_trimmed_without_changing_content() -> None:
    """앞뒤 공백은 제거하고 질문 본문의 공백과 개행은 유지한다."""
    request = MessageCreateRequest(question=" \t FastAPI  질문\n두 번째 줄 \n")
    assert request.question == "FastAPI  질문\n두 번째 줄"


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("가", "가"),
        ("가" * 1000, "가" * 1000),
        (" \t" + "가" * 1000 + "\n\u2003", "가" * 1000),
        ("가" * 499 + " \n" + "나" * 499, "가" * 499 + " \n" + "나" * 499),
        ("😀" * 1000, "😀" * 1000),
        ("👩‍💻" * 333 + "가", "👩‍💻" * 333 + "가"),
        ("가" * 500, "가" * 500),
    ],
    ids=[
        "minimum",
        "maximum",
        "trim-before-length-check",
        "internal-whitespace",
        "emoji-code-points",
        "combined-emoji",
        "no-unicode-normalization",
    ],
)
def test_question_length_accepts_boundaries_and_preserves_content(
    question: str, expected: str
) -> None:
    """길이 경계값을 허용하고 앞뒤 공백 외의 문자와 내부 공백은 유지한다."""
    assert MessageCreateRequest(question=question).question == expected


@pytest.mark.parametrize(
    "question",
    [
        "가" * 1001,
        "  " + "가" * 1001 + "\n",
        "가" * 500 + " " + "나" * 500,
        "가" * 500 + "\n" + "나" * 500,
        "😀" * 1001,
        "👩‍💻" * 334,
        "가" * 501,
    ],
    ids=[
        "over-maximum",
        "over-maximum-after-trim",
        "internal-space-counts",
        "internal-newline-counts",
        "emoji-over-maximum",
        "combined-emoji-over-maximum",
        "decomposed-hangul-over-maximum",
    ],
)
def test_question_over_length_limit_is_rejected(question: str) -> None:
    """내부 공백과 Unicode 코드 포인트를 포함해 1,000자 초과를 거절한다."""
    with pytest.raises(ValidationError) as error:
        MessageCreateRequest(question=question)
    assert error.value.errors()[0]["type"] == "string_too_long"


@pytest.mark.parametrize(
    "question",
    ["", " \t\n ", "\u2003", None, 1, True, [], {}],
    ids=["empty", "whitespace", "unicode-space", "null", "int", "bool", "list", "dict"],
)
def test_empty_and_non_string_questions_are_rejected(question: object) -> None:
    """빈 질문·공백 질문·문자열이 아닌 질문을 거절한다."""
    with pytest.raises(ValidationError):
        MessageCreateRequest.model_validate({"question": question})


def test_missing_question_is_rejected() -> None:
    """질문 필드가 누락된 요청을 거절한다."""
    with pytest.raises(ValidationError):
        MessageCreateRequest.model_validate({})
