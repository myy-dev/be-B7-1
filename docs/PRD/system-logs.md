# 시스템 이벤트 로그

요청·회원 인증·AI 호출·DB 저장 이벤트를 공통 형식으로 기록합니다. 관리자는 로그 파일을 조회해 요청별 처리 결과를 확인합니다.

## 기록 방식

한 줄에 JSON 하나씩 기록하는 JSONL 파일을 사용합니다. 공용 `Settings.system_log_path`로 경로를 관리합니다. 기본값·환경 변수·Railway 볼륨·파일 확인과 쓰기 실패 대응은 [운영 로그 안내](../OPERATIONS.md#서버-로그와-요청-추적)를 따릅니다.

## 필드

| 필드 | 필수 | 설명 |
| --- | --- | --- |
| `timestamp` | O | ISO 8601 (UTC). 예: `2026-09-30T05:00:00Z` |
| `level` | O | `INFO`, `WARNING`, `ERROR` |
| `event` | O | 무슨 일인지. 아래 이벤트 이름 참고 |
| `request_id` | | 요청을 식별하는 UUID4 |
| `user_id` | | 관련 회원 ID. 파일은 문자열, 관리자 응답은 정수 |
| `method` | | HTTP 요청 메서드 |
| `path` | | 쿼리 문자열을 제외한 요청 경로 |
| `status_code` | | HTTP 응답 상태 코드 |

관리자 API는 위 필드를 반환합니다. 파일에는 `chat_id`, `result`, `error_code`, `duration_ms`, `exception_type`도 포함되므로 상세 원인은 원본 로그에서 확인합니다. 질문·답변 원문, 비밀번호, 토큰, API 키와 스택 트레이스는 기록하지 않습니다.

## 이벤트 이름

이벤트 종류에 따라 다음 이름을 사용합니다.

| 영역 | 이벤트 |
| --- | --- |
| 요청 | `request_received`, `request_completed`, `request_failed` |
| 공통 오류 | `api_error` |
| AI 호출 | `ai_call_started`, `ai_call_succeeded`, `ai_call_failed` |
| DB 저장 | `db_save_succeeded`, `db_save_failed` |
| 회원 | `user_signed_up`, `user_logged_in`, `user_login_failed` |

AI 이벤트는 서비스 호출 전체의 시작과 최종 결과입니다. 재시도 횟수별 이벤트는 별도로 남기지 않습니다. 대화 원문은 DB에서 확인합니다.

`request_failed`·`ai_call_failed`·`db_save_failed` 또는 상태 코드 500 이상은 `ERROR`, 그 외 로그인 실패는 `WARNING`, 나머지는 `INFO`로 기록합니다. 따라서 401·403 등의 요청 완료는 `INFO`입니다.

## 예시

AI 실패 후 실패 상태를 DB에 저장한 로그의 주요 필드입니다. 요청 수신 시에는 인증 전이므로 `user_id`가 null입니다.

```jsonl
{"timestamp":"2026-09-30T05:00:00Z","level":"INFO","event":"request_received","request_id":"16fd2706-8baf-433b-82eb-8c7fada847da","method":"POST","path":"/api/v1/chats/00000000-0000-4000-8000-000000000001/messages","user_id":null}
{"timestamp":"2026-09-30T05:00:01Z","level":"INFO","event":"ai_call_started","request_id":"16fd2706-8baf-433b-82eb-8c7fada847da","user_id":"42"}
{"timestamp":"2026-09-30T05:00:03Z","level":"ERROR","event":"ai_call_failed","request_id":"16fd2706-8baf-433b-82eb-8c7fada847da","user_id":"42"}
{"timestamp":"2026-09-30T05:00:03Z","level":"INFO","event":"db_save_succeeded","request_id":"16fd2706-8baf-433b-82eb-8c7fada847da","user_id":"42"}
{"timestamp":"2026-09-30T05:00:03Z","level":"ERROR","event":"request_completed","request_id":"16fd2706-8baf-433b-82eb-8c7fada847da","method":"POST","path":"/api/v1/chats/00000000-0000-4000-8000-000000000001/messages","user_id":"42","status_code":502}
```

## 관리자 조회

관리자 토큰으로 `GET /api/v1/admin/system-logs`를 호출합니다. 이벤트·레벨·기간으로 필터링하고 최신순으로 조회합니다. 필터·페이지 형식은 [Swagger](https://be-b7-1-development.up.railway.app/docs)의 `admin` 항목에서 확인합니다.

```
GET /api/v1/admin/system-logs?level=ERROR&event=ai_call_failed
```

## 조회 규칙

- 시각은 UTC로 기록합니다. 조회에서는 다른 시간대도 UTC로 변환하며 시간대가 없는 시각은 UTC로 해석합니다.
- 선택 필드는 값이 없으면 null 또는 생략할 수 있습니다.
- 기존 파일의 `http_status`도 읽어 `status_code`로 반환합니다. 두 필드가 함께 있으면 `status_code`를 우선합니다.
- JSON 문법·필수 필드·날짜·자료형이 잘못된 줄은 제외합니다. 유효한 로그만 집계·필터·페이지에 포함하며 원본 파일은 수정하지 않습니다.
