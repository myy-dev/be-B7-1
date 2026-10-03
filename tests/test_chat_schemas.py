"""채팅 API 명세의 응답 구조와 상태별 데이터 규칙을 검증한다."""

import json
import re
import unittest
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from app.schemas.chat import (
    ChatDetailResponse,
    ChatListResponse,
    ChatResponse,
    MessageResponse,
)
from app.schemas.error import ErrorResponse


class ChatSchemaTests(unittest.TestCase):
    """명세의 JSON 예제와 상태·시각 규칙을 확인한다."""

    def test_api_response_examples_round_trip(self) -> None:
        """명세서의 응답 예제가 필드·값 변경 없이 직렬화되는지 확인한다."""
        api_path = Path(__file__).resolve().parents[1] / "docs/PRD/AI-CHAT-API.md"
        examples = re.findall(r"```json\n(.*?)\n```", api_path.read_text(), re.S)
        verified = 0
        for example in examples:
            data = json.loads(example)
            if "question" in data and "request_id" not in data:
                continue
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
            with self.subTest(schema=schema.__name__):
                self.assertEqual(
                    schema.model_validate(data).model_dump(mode="json"), data
                )
            verified += 1
        self.assertEqual(verified, 5)

    def test_pending_and_failed_keep_null_fields(self) -> None:
        """처리 중·실패 기록이 명세의 null 필드를 모두 반환하는지 확인한다."""
        data = self._pending_record()
        pending = MessageResponse.model_validate(data).model_dump(mode="json")
        self.assertEqual(set(pending), set(data))
        for field in ("answer", "error_code", "finished_at"):
            self.assertIsNone(pending[field])

        data.update(
            status="failed",
            error_code="AI_TIMEOUT",
            finished_at="2026-10-03T07:00:30Z",
        )
        failed = MessageResponse.model_validate(data).model_dump(mode="json")
        self.assertIsNone(failed["answer"])
        self.assertEqual(failed["error_code"], "AI_TIMEOUT")
        self.assertEqual(failed["finished_at"], "2026-10-03T07:00:30Z")

    def test_inconsistent_status_is_rejected(self) -> None:
        """상태와 결과 필드가 모순인 기록이 거절되는지 확인한다."""
        for changes in (
            {"answer": "아직 완료되지 않은 답변"},
            {"status": "completed"},
            {"status": "failed"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                MessageResponse.model_validate(self._pending_record() | changes)

    def test_empty_collections(self) -> None:
        """채팅방과 대화 기록이 없을 때 빈 배열을 유지하는지 확인한다."""
        self.assertEqual(ChatListResponse(items=[]).model_dump(), {"items": []})
        detail = ChatDetailResponse(
            chat_id=uuid4(), created_at=datetime.now(UTC), messages=[]
        )
        self.assertEqual(detail.model_dump(mode="json")["messages"], [])

    def test_timestamps_are_normalized_to_utc(self) -> None:
        """시간대가 있는 시각은 UTC로 변환하고 시간대 없는 값은 거절한다."""
        chat_id = uuid4()
        response = ChatResponse(
            chat_id=chat_id, created_at="2026-10-03T16:00:00+09:00"
        )
        self.assertEqual(
            response.model_dump(mode="json")["created_at"], "2026-10-03T07:00:00Z"
        )
        with self.assertRaises(ValidationError):
            ChatResponse(chat_id=chat_id, created_at="2026-10-03T07:00:00")

    @staticmethod
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
