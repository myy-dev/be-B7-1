# 시스템 이벤트 로그 작성 안내

관리자 화면의 시스템 로그 조회는 백엔드가 남긴 로그 파일을 읽어 보여준다. 그래서 **각 담당이 자기 영역에서 로그를 같은 형식으로 남겨야** 조회가 한 번에 된다.

## 어떻게 남기나

한 줄에 JSON 하나씩(JSONL) 남긴다. 파일은 하나로 모은다.

```
logs/system.jsonl
```

경로는 공용 설정 `Settings.system_log_path`가 갖고 있다(`app/core/config.py`). 기본값은 위 경로이고, `SYSTEM_LOG_PATH` 환경 변수나 `.env`로 바꾼다. 개발할 땐 각자 로컬에 남기고, 배포할 땐 한 파일에 쌓이도록 맞춘다.

## 필드

| 필드 | 필수 | 설명 |
| --- | --- | --- |
| `timestamp` | O | ISO 8601 (UTC). 예: `2026-09-30T05:00:00Z` |
| `level` | O | `INFO`, `WARNING`, `ERROR` |
| `event` | O | 무슨 일인지. 아래 이벤트 이름 참고 |
| `request_id` | | 요청 하나를 따라가는 값. 있으면 넣는다 |
| `user_id` | | 관련 사용자. 있으면 넣는다 |

이 다섯 개만 관리자 조회가 쓴다. 다른 값을 더 넣어도 조회에는 안 나온다.

## 이벤트 이름

같은 일은 같은 이름으로 남긴다. 아래를 기본으로 쓰고, 더 필요하면 여기에 추가해서 팀에 알린다.

| 영역 | 이벤트 |
| --- | --- |
| 요청 | `request_received` |
| AI 호출 | `ai_call_started`, `ai_call_succeeded`, `ai_call_failed` |
| DB 저장 | `db_save_succeeded`, `db_save_failed` |
| 회원 | `user_signed_up`, `user_logged_in`, `user_login_failed` |

## 예시

```json
{"timestamp":"2026-09-30T05:00:00Z","level":"INFO","event":"request_received","request_id":"abc-123","user_id":42}
{"timestamp":"2026-09-30T05:00:01Z","level":"INFO","event":"ai_call_started","request_id":"abc-123","user_id":42}
{"timestamp":"2026-09-30T05:00:03Z","level":"ERROR","event":"ai_call_failed","request_id":"abc-123","user_id":42}
{"timestamp":"2026-09-30T05:00:03Z","level":"INFO","event":"db_save_succeeded","request_id":"abc-123","user_id":42}
```

## 관리자 쪽에서 보는 방법

`GET /api/v1/admin/system-logs`로 `event`, `level`, `start`, `end`를 걸러 최신순으로 받는다.

```
GET /api/v1/admin/system-logs?level=ERROR&event=ai_call_failed
```

## 주의

- `timestamp`는 UTC로 맞춘다. 시간대가 섞이면 기간 필터가 어긋난다.
- 값이 없는 선택 필드는 아예 빼도 된다. 빈 문자열보다 생략이 낫다.
- 로그를 남기다 실패해도 본 요청은 죽이지 않는다. 로그는 부가 기능이다.

- 조회 시 JSON 문법, 필수 필드, 날짜와 필드 자료형이 올바르지 않은 줄은 건너뛴다. 유효한 로그만 총건수·필터·페이지에 포함하며 원본 파일은 수정하지 않는다.
