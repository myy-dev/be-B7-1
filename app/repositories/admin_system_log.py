import json
from datetime import UTC, datetime
from pathlib import Path

from app.repositories.admin_repositories import SystemLogRepository

KNOWN_FIELDS = ("timestamp", "level", "event", "request_id", "user_id")


def parse_timestamp(value: object) -> datetime | None:
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
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                row = {k: record.get(k) for k in KNOWN_FIELDS if k in record}
                row["_ts"] = parse_timestamp(record.get("timestamp"))
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
            rows = [r for r in rows if r["_ts"] is not None and r["_ts"] >= start]
        if end is not None:
            rows = [r for r in rows if r["_ts"] is not None and r["_ts"] <= end]

        rows.sort(
            key=lambda r: r["_ts"] or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )

        total = len(rows)
        begin = (page - 1) * size
        window = rows[begin : begin + size]
        cleaned = [{k: v for k, v in r.items() if k != "_ts"} for r in window]
        return cleaned, total
