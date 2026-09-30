import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

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
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


class SystemLogFileRepository(SystemLogRepository):
    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def _read_all(self) -> list[dict]:
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
