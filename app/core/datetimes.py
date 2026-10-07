"""조회 파라미터 시각을 UTC 기준으로 맞춘다.

기간 필터는 로그 기록의 시각과 비교한다. 기록 쪽은 파싱할 때 타임존을 붙이는데
조회 파라미터는 붙지 않은 채 들어올 수 있어(예: 2026-09-30T04:00:00), naive와
aware를 비교하다 TypeError가 나고 500으로 나갔다.

그래서 경계에서 한 번 맞춘다. 타임존이 없으면 UTC로 간주하고, 있는 값은 UTC로
환산한다. 기록 파싱(parse_timestamp)과 같은 규칙을 쓰므로 두 기준이 어긋나지
않는다. 422로 거절하는 방법도 있지만, 타임존 없이 호출하던 클라이언트를 깨뜨리지
않는 쪽을 택했다.
"""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator
from sqlalchemy import DateTime
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


def to_utc(value: datetime) -> datetime:
    """타임존이 없으면 UTC로 간주하고, 있으면 UTC로 환산한다."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


# 쿼리·본문에서 받는 시각. 해석 즉시 UTC aware가 된다.
UtcDateTime = Annotated[datetime, AfterValidator(to_utc)]


class UTCDateTimeType(TypeDecorator[datetime]):
    """DB에 UTC 시각을 저장하고 조회 결과에 UTC 시간대를 복원한다."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        """저장 시각을 UTC로 맞추고 SQLite에는 시간대를 제외해 전달한다.

        Args:
            value: 저장할 시각 또는 null.
            dialect: 값을 저장하는 DB 방언.

        Returns:
            UTC로 변환한 시각 또는 null.
        """
        if value is None:
            return None
        normalized = to_utc(value)
        if dialect.name == "sqlite":
            return normalized.replace(tzinfo=None)
        return normalized

    def process_result_value(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        """DB에서 조회한 시각을 UTC 시간대가 있는 값으로 반환한다.

        Args:
            value: DB에서 조회한 시각 또는 null.
            dialect: 값을 조회한 DB 방언.

        Returns:
            UTC 시간대를 가진 시각 또는 null.
        """
        return None if value is None else to_utc(value)
