"""격리된 SQLite에서 채팅 기록의 영속성과 DB 제약을 검증한다."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from sqlite3 import Connection
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, SAWarning
from sqlalchemy.orm import Session
from sqlalchemy.pool import ConnectionPoolEntry

from app.core.database import Base
from app.models import Chat, ChatLog
from app.models.user import User


def _create_engine(path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{path}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(
        connection: Connection, connection_record: ConnectionPoolEntry
    ) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    return engine


@pytest.fixture
def model_engine(tmp_path: Path) -> Iterator[Engine]:
    """테스트마다 외래키 검사가 켜진 독립 SQLite 파일을 제공한다.

    Args:
        tmp_path: pytest가 제공한 임시 디렉터리.

    Yields:
        채팅 테이블이 생성된 SQLite 엔진.
    """
    engine = _create_engine(tmp_path / "chat-models.db")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                User(id=1, username="test_user", password_hash="test-only", name="회원"),
                User(
                    id=9_000_000_001,
                    username="large_owner",
                    password_hash="test-only",
                    name="큰 ID 회원",
                ),
            ]
        )
        session.commit()
    try:
        yield engine
    finally:
        engine.dispose()


def _create_chat(engine: Engine) -> UUID:
    with Session(engine) as session:
        chat = Chat(user_id=9_000_000_001)
        session.add(chat)
        session.commit()
        return chat.chat_id


def test_chat_defaults_and_large_owner_id(model_engine: Engine) -> None:
    """서버 생성 UUID4·UTC 시각과 큰 정수 소유자 ID가 재조회 후 유지된다.

    Args:
        model_engine: 테스트 전용 SQLite 엔진.
    """
    first_id = _create_chat(model_engine)
    second_id = _create_chat(model_engine)
    assert first_id != second_id
    assert first_id.version == second_id.version == 4
    with Session(model_engine) as session:
        chat = session.get(Chat, first_id)
        assert chat is not None
        assert chat.user_id == 9_000_000_001
        assert chat.created_at.tzinfo is UTC
        assert chat.deleted_at is None


def test_deleted_at_round_trip_preserves_chat_and_messages(
    model_engine: Engine,
) -> None:
    """삭제 시각을 UTC로 재조회하며 채팅방과 대화 기록을 그대로 유지한다.

    Args:
        model_engine: 외래키가 적용된 테스트용 SQLite 엔진.
    """
    chat_id = _create_chat(model_engine)
    request_id = uuid4()
    with Session(model_engine) as session:
        session.add(
            ChatLog(
                request_id=request_id,
                chat_id=chat_id,
                question="보존할 질문",
                model="test-model",
            )
        )
        chat = session.get(Chat, chat_id)
        assert chat is not None
        chat.deleted_at = datetime(2026, 10, 9, 12, tzinfo=timezone(timedelta(hours=9)))
        session.commit()

    with Session(model_engine) as session:
        chat = session.get(Chat, chat_id)
        assert chat is not None
        assert chat.deleted_at == datetime(2026, 10, 9, 3, tzinfo=UTC)
        assert chat.deleted_at.tzinfo is UTC
        log = session.get(ChatLog, request_id)
        assert log is not None
        assert log.question == "보존할 질문"
        assert log.status == "pending"
        assert session.execute(text("PRAGMA foreign_key_check")).all() == []


def test_request_id_and_results_survive_engine_restart(model_engine: Engine) -> None:
    """질문을 완료로 갱신한 뒤 새 엔진에서도 같은 요청 ID와 결과를 조회한다.

    Args:
        model_engine: 테스트 전용 SQLite 엔진.
    """
    chat_id = _create_chat(model_engine)
    request_id = uuid4()
    with Session(model_engine) as session:
        session.add(
            ChatLog(
                request_id=request_id,
                chat_id=chat_id,
                question="첫 질문",
                model="test-model",
            )
        )
        session.commit()
    with Session(model_engine) as session:
        log = session.get(ChatLog, request_id)
        assert log is not None
        assert log.status == "pending"
        assert log.created_at.tzinfo is UTC
        assert log.answer is log.error_code is log.finished_at is None
        log.status = "completed"
        log.answer = "첫 답변"
        log.finished_at = datetime.now(UTC)
        session.commit()

    assert model_engine.url.database is not None
    database_path = Path(model_engine.url.database)
    model_engine.dispose()
    restarted_engine = _create_engine(database_path)
    try:
        with Session(restarted_engine) as session:
            logs = session.scalars(select(ChatLog)).all()
            assert len(logs) == 1
            log = logs[0]
            assert log.request_id == request_id
            assert log.chat_id == chat_id
            assert log.question == "첫 질문"
            assert log.answer == "첫 답변"
            assert log.model == "test-model"
            assert log.status == "completed"
            assert log.error_code is None
            assert log.finished_at is not None
            assert log.finished_at.tzinfo is UTC
    finally:
        restarted_engine.dispose()


@pytest.mark.parametrize(
    "created_at",
    [
        datetime(2026, 10, 5, 12, tzinfo=timezone(timedelta(hours=9))),
        datetime(2026, 10, 4, 20, tzinfo=timezone(timedelta(hours=-7))),
        datetime(2026, 10, 5, 3),
    ],
)
def test_utc_storage_and_round_trip(
    model_engine: Engine, created_at: datetime
) -> None:
    """시간대가 다른 입력을 저장 전에 UTC로 맞추고 조회할 때 시간대를 복원한다.

    Args:
        model_engine: 테스트 전용 SQLite 엔진.
        created_at: 같은 UTC 시각을 나타내는 서로 다른 시간대의 값.
    """
    chat_id = uuid4()
    with Session(model_engine) as session:
        session.add(Chat(chat_id=chat_id, user_id=1, created_at=created_at))
        session.commit()
    with Session(model_engine) as session:
        chat = session.get(Chat, chat_id)
        assert chat is not None
        assert chat.created_at == datetime(2026, 10, 5, 3, tzinfo=UTC)
        assert chat.created_at.tzinfo is UTC
        stored = session.scalar(text("SELECT created_at FROM chats"))
        assert stored == "2026-10-05 03:00:00.000000"


@pytest.mark.parametrize(
    ("status", "answer", "error_code", "finished_at"),
    [
        ("pending", None, None, None),
        ("completed", "답변", None, datetime(2026, 10, 5, 3, tzinfo=UTC)),
        ("failed", None, "AI_TIMEOUT", datetime(2026, 10, 5, 3, tzinfo=UTC)),
    ],
)
def test_valid_status_combinations(
    model_engine: Engine,
    status: str,
    answer: str | None,
    error_code: str | None,
    finished_at: datetime | None,
) -> None:
    """각 처리 상태의 답변·오류 코드·종료 시각 조합이 그대로 저장된다.

    Args:
        model_engine: 테스트 전용 SQLite 엔진.
        status: 저장할 처리 상태.
        answer: 상태에 맞는 답변 또는 null.
        error_code: 상태에 맞는 오류 코드 또는 null.
        finished_at: 상태에 맞는 종료 시각 또는 null.
    """
    request_id = uuid4()
    chat_id = _create_chat(model_engine)
    with Session(model_engine) as session:
        session.add(
            ChatLog(
                request_id=request_id,
                chat_id=chat_id,
                question="질문",
                model="test-model",
                status=status,
                answer=answer,
                error_code=error_code,
                finished_at=finished_at,
            )
        )
        session.commit()
    with Session(model_engine) as session:
        log = session.get(ChatLog, request_id)
        assert log is not None
        assert (log.status, log.answer, log.error_code, log.finished_at) == (
            status,
            answer,
            error_code,
            finished_at,
        )


@pytest.mark.parametrize(
    ("status", "answer", "error_code", "finished_at"),
    [
        ("unknown", None, None, None),
        ("pending", "답변", None, None),
        ("pending", None, "AI_TIMEOUT", None),
        ("pending", None, None, datetime(2026, 10, 5, tzinfo=UTC)),
        ("completed", None, None, datetime(2026, 10, 5, tzinfo=UTC)),
        ("completed", "답변", "DB_ERROR", datetime(2026, 10, 5, tzinfo=UTC)),
        ("completed", "답변", None, None),
        ("failed", "답변", "AI_TIMEOUT", datetime(2026, 10, 5, tzinfo=UTC)),
        ("failed", None, None, datetime(2026, 10, 5, tzinfo=UTC)),
        ("failed", None, "AI_TIMEOUT", None),
    ],
)
def test_invalid_status_combinations_are_rejected(
    model_engine: Engine,
    status: str,
    answer: str | None,
    error_code: str | None,
    finished_at: datetime | None,
) -> None:
    """잘못된 처리 상태와 결과 필드 조합은 DB 자체에서 거절된다.

    Args:
        model_engine: 테스트 전용 SQLite 엔진.
        status: 잘못된 상태 또는 결과 필드와 맞지 않는 상태.
        answer: 검증할 답변 값.
        error_code: 검증할 오류 코드 값.
        finished_at: 검증할 종료 시각 값.
    """
    chat_id = _create_chat(model_engine)
    with Session(model_engine) as session:
        session.add(
            ChatLog(
                request_id=uuid4(),
                chat_id=chat_id,
                question="질문",
                model="test-model",
                status=status,
                answer=answer,
                error_code=error_code,
                finished_at=finished_at,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        assert session.scalars(select(ChatLog)).all() == []


def test_nonexistent_chat_foreign_key_is_rejected(model_engine: Engine) -> None:
    """소속 채팅방이 없는 기록은 외래키 검사로 저장되지 않는다.

    Args:
        model_engine: 테스트 전용 SQLite 엔진.
    """
    with Session(model_engine) as session:
        assert session.scalar(text("PRAGMA foreign_keys")) == 1
        session.add(
            ChatLog(
                request_id=uuid4(),
                chat_id=uuid4(),
                question="질문",
                model="test-model",
            )
        )
        with pytest.raises(IntegrityError, match="FOREIGN KEY"):
            session.commit()


def test_missing_request_id_is_not_generated(model_engine: Engine) -> None:
    """최초 요청 ID를 전달하지 않은 기록에 새로운 ID를 생성하지 않는다.

    Args:
        model_engine: 테스트 전용 SQLite 엔진.
    """
    chat_id = _create_chat(model_engine)
    with Session(model_engine) as session:
        session.add(ChatLog(chat_id=chat_id, question="질문", model="test-model"))
        with pytest.warns(SAWarning, match="primary key"):
            with pytest.raises(IntegrityError, match="request_id"):
                session.commit()


@pytest.mark.parametrize(("question", "model"), [(None, "test-model"), ("질문", None)])
def test_required_question_and_model_are_not_null(
    model_engine: Engine, question: str | None, model: str | None
) -> None:
    """질문 원문과 호출 모델이 없는 기록은 DB에서 거절된다.

    Args:
        model_engine: 테스트 전용 SQLite 엔진.
        question: 검증할 질문 값.
        model: 검증할 모델 값.
    """
    chat_id = _create_chat(model_engine)
    with Session(model_engine) as session:
        session.add(
            ChatLog(
                request_id=uuid4(), chat_id=chat_id, question=question, model=model
            )
        )
        with pytest.raises(IntegrityError, match="NOT NULL"):
            session.commit()


def test_nonexistent_user_foreign_key_is_rejected(model_engine: Engine) -> None:
    """없는 사용자 ID로 채팅을 저장하면 외래키 검사로 거절한다.

    Args:
        model_engine: 외래키 검사가 켜진 테스트용 SQLite 엔진.
    """
    with Session(model_engine) as session:
        session.add(Chat(user_id=9999))
        with pytest.raises(IntegrityError, match="FOREIGN KEY"):
            session.commit()
        session.rollback()
        assert session.scalars(select(Chat)).all() == []


def test_owner_update_requires_existing_user(model_engine: Engine) -> None:
    """채팅 소유자를 없는 사용자로 바꾸면 거절하고 기존 소유자를 유지한다.

    Args:
        model_engine: 외래키 검사가 켜진 테스트용 SQLite 엔진.
    """
    chat_id = _create_chat(model_engine)
    with Session(model_engine) as session:
        chat = session.get(Chat, chat_id)
        assert chat is not None
        chat.user_id = 9999
        with pytest.raises(IntegrityError, match="FOREIGN KEY"):
            session.commit()
        session.rollback()
        assert chat.user_id == 9_000_000_001


def test_referenced_user_delete_preserves_chat(model_engine: Engine) -> None:
    """삭제 정책 확정 전 외래키 기본 동작이 고아 채팅 생성을 막는다.

    Args:
        model_engine: 외래키 검사가 켜진 테스트용 SQLite 엔진.
    """
    chat_id = _create_chat(model_engine)
    with Session(model_engine) as session:
        user = session.get(User, 9_000_000_001)
        assert user is not None
        session.delete(user)
        with pytest.raises(IntegrityError, match="FOREIGN KEY"):
            session.commit()
        session.rollback()
        assert session.get(User, 9_000_000_001) is not None
        assert session.get(Chat, chat_id) is not None
