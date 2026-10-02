"""시스템 이벤트 로그(JSONL) 파일 조회.

기록은 백엔드 각 담당이 같은 파일에 남기고 조회만 여기서 한다. 요청마다 파일
전체를 읽어 파이썬에서 거르고 정렬하므로, 로그가 커지면 이 지점이 가장 먼저
느려진다(기간 필터를 읽기 단계로 내리거나 DB로 옮기는 것이 다음 후보).
"""

import json
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from app.core.datetimes import to_utc
from app.core.pagination import slice_page
from app.repositories.admin_repositories import SystemLogRepository
from app.schemas.admin import SystemLogItem


def parse_timestamp(value: object) -> datetime | None:
    # 외부 로그 원문이라 날짜가 깨질 수 있다. 파싱 불가는 None으로 알린다.
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    # 타임존 없는 기록은 UTC로 간주한다(조회 파라미터와 같은 규칙).
    return to_utc(parsed)


class SystemLogFileRepository(SystemLogRepository):
    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def _read_all(self) -> list[dict]:
        # 파일이 없으면 빈 목록이다(조회는 200·빈 페이지).
        # 읽기 권한 오류 같은 다른 실패는 지금은 500으로 나간다.
        if not self.path.exists():
            return []
        rows: list[dict] = []
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                # 깨진 줄 하나가 전체 조회를 막지 않도록, 형식이 어긋난 줄은 건너뛴다.
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                timestamp = parse_timestamp(record.get("timestamp"))
                if timestamp is None:
                    continue
                try:
                    item = SystemLogItem.model_validate(
                        {**record, "timestamp": timestamp}
                    )
                except ValidationError:
                    continue
                row = item.model_dump()
                row["_ts"] = timestamp
                rows.append(row)
        return rows

    async def query(
        self, level, event, start, end, page, size
    ) -> tuple[list[dict], int]:
        rows = self._read_all()

        if level:
            rows = [r for r in rows if r.get("level") == level]
        if event:
            rows = [r for r in rows if r.get("event") == event]
        if start is not None:
            rows = [r for r in rows if r["_ts"] >= start]
        if end is not None:
            rows = [r for r in rows if r["_ts"] <= end]

        rows.sort(key=lambda r: r["_ts"], reverse=True)

        window, total = slice_page(rows, page, size)
        cleaned = [{k: v for k, v in r.items() if k != "_ts"} for r in window]
        return cleaned, total
