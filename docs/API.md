# API 안내

기본 경로는 `/api/v1`입니다. 모든 예시는 로컬 서버 기준이며 응답 ID·시각·답변은 예시입니다. 전체 필드 스키마는 실행 중인 `/docs`, `/redoc`, `/openapi.json`에서 확인합니다.

## 엔드포인트

| 메서드·경로 | 성공 | 인증·설명 |
| --- | --- | --- |
| `GET /health` | 200 | 공개, DB 연결 검사 |
| `POST /api/v1/auth/signup` | 201 | 공개, 회원가입 |
| `POST /api/v1/auth/login` | 200 | 공개, JWT 발급 |
| `POST /api/v1/auth/logout` | 204 | Bearer, 현재 토큰 폐기 |
| `POST /api/v1/chats` | 201 | Bearer, 채팅방 생성 |
| `GET /api/v1/chats` | 200 | Bearer, 본인 채팅방 목록 |
| `GET /api/v1/chats/{chat_id}` | 200 | Bearer, 본인 채팅방과 전체 기록 |
| `DELETE /api/v1/chats/{chat_id}` | 204 | Bearer, 논리 삭제 |
| `POST /api/v1/chats/{chat_id}/messages` | 201 | Bearer, 질문·AI 답변 저장 |
| `GET /api/v1/admin/users` | 200 | 관리자, 회원 목록 |
| `GET /api/v1/admin/users/{user_id}` | 200 | 관리자, 회원 상세 |
| `GET /api/v1/admin/logs` | 200 | 관리자, 대화 기록 |
| `GET /api/v1/admin/sessions` | 200 | 관리자, 회원별 세션 |
| `GET /api/v1/admin/sessions/{chat_id}` | 200 | 관리자, 세션 상세 |
| `GET /api/v1/admin/system-logs` | 200 | 관리자, 이벤트 로그 |

현재 `main`에는 내 정보 조회 API가 없습니다. 채팅 라우터의 일부 Swagger 설명에 남은 사용자 ID `1` 테스트 문구와 달리 실제 요청에는 JWT가 필요합니다.

## 인증과 접근 제어

로그인 후 `Authorization: Bearer <access_token>`을 보냅니다. JWT는 HS256 서명, 회원 ID(`sub`), 발급 시각(`iat`), 만료 시각(`exp`), 토큰 ID(`jti`)를 포함합니다. 기본 만료는 30분입니다. 서버는 서명·만료·회원 존재·토큰 폐기 여부를 확인합니다. 로그아웃은 현재 토큰만 폐기하며 다른 로그인 토큰까지 폐기하지 않습니다.

사용자는 본인 채팅방에만 접근합니다. 다른 사람의 채팅방, 삭제된 채팅방, 없는 채팅방은 모두 `404 CHAT_NOT_FOUND`입니다. 관리자 API는 DB의 `role=admin`을 확인하며 일반 회원은 `403 FORBIDDEN`입니다. 회원가입은 관리자 권한 입력을 받지 않습니다. 관리자 생성·승격 API는 없습니다.

## 요청·응답 예시

```bash
curl -X POST http://127.0.0.1:8000/api/v1/auth/signup \
  -H 'Content-Type: application/json' \
  -d '{"username":"tester01","password":"Example123!","name":"테스터"}'
```

```json
{"id":1,"username":"tester01","name":"테스터","created_at":"2026-10-09T00:00:00Z"}
```

```bash
curl -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"tester01","password":"Example123!"}'
```

```json
{"access_token":"<발급된 JWT>","token_type":"bearer","expires_in":1800}
```

셸의 `TOKEN`에 발급된 토큰을 넣고 요청합니다.

```bash
curl -X POST http://127.0.0.1:8000/api/v1/chats \
  -H "Authorization: Bearer $TOKEN"
```

```json
{"chat_id":"e6100748-b7f0-48e6-a264-7c20a748cf93","created_at":"2026-10-09T00:00:01Z"}
```

`CHAT_ID`에 생성 응답의 `chat_id`를 넣습니다.

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/chats/$CHAT_ID/messages" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"question":"FastAPI가 뭐야?"}'
```

```json
{
  "request_id":"16fd2706-8baf-433b-82eb-8c7fada847da",
  "chat_id":"e6100748-b7f0-48e6-a264-7c20a748cf93",
  "question":"FastAPI가 뭐야?",
  "answer":"Python으로 웹 API를 만드는 프레임워크입니다.",
  "status":"completed",
  "error_code":null,
  "created_at":"2026-10-09T00:00:02Z",
  "finished_at":"2026-10-09T00:00:04Z"
}
```

목록은 `{"items":[채팅방 응답]}`, 상세는 `chat_id`, `created_at`, `messages` 배열을 반환합니다. `messages`에는 pending·completed·failed 기록이 포함됩니다. 삭제와 로그아웃 성공 응답은 본문 없는 204입니다.

관리자 목록은 `{"items":[],"total":0,"page":1,"size":20}` 형식입니다. 상세 응답은 페이지 형식을 사용하지 않습니다.

```bash
curl 'http://127.0.0.1:8000/api/v1/admin/logs?user_id=1&page=1&size=20' \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

관리자 목록 공통 `page`는 1 이상, `size`는 1~100(기본 20)입니다. 대화 로그는 `user_id`, `start`, `end`; 세션 목록은 필수 `user_id`; 시스템 로그는 `level`, `event`, `start`, `end` 필터를 지원합니다. 날짜는 시간대가 있는 ISO 8601 값으로 전달합니다. 예: `2026-10-09T00:00:00Z`.

## 입력 검증

| 입력 | 규칙 |
| --- | --- |
| 회원가입 username | 4~20자, 영문·숫자·밑줄, 소문자로 정규화 |
| 회원가입 password | 8~128자, ASCII 영문·숫자·특수문자 각각 포함, 공백 금지 |
| 회원가입 name | 앞뒤 공백 제거 후 1~50자 |
| 로그인 | username 규칙 동일, password 8~128자 |
| 회원가입·로그인 추가 필드 | 거절 (`extra=forbid`) |
| 질문 question | 문자열, 앞뒤 공백 제거 후 최소 1자, 최대 길이 제한 없음 |
| 채팅 API chat_id | UUID |
| 관리자 기간 | 시간대가 있는 날짜·시각 |

## 오류 코드

```json
{"error":{"code":"AI_TIMEOUT","message":"응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.","request_id":"16fd2706-8baf-433b-82eb-8c7fada847da"}}
```

요청마다 서버가 UUID를 생성하고 `X-Request-ID` 헤더로 반환합니다. 오류의 `request_id`로 이벤트 로그를 찾습니다.

| HTTP | code | 의미 |
| --- | --- | --- |
| 401 | `UNAUTHORIZED` | 토큰 누락·유효하지 않음·폐기·회원 없음 |
| 401 | `INVALID_CREDENTIALS` | 아이디 또는 비밀번호 불일치 |
| 403 | `FORBIDDEN` | 관리자 권한 없음 |
| 404 | `CHAT_NOT_FOUND` | 접근 가능한 미삭제 채팅방 없음 |
| 404 | `USER_NOT_FOUND`, `SESSION_NOT_FOUND` | 관리자 상세 조회 대상 없음 |
| 404 / 405 | `NOT_FOUND` / `METHOD_NOT_ALLOWED` | 경로 없음 / 허용하지 않는 메서드 |
| 409 | `USERNAME_TAKEN` | 중복 아이디 |
| 409 | `CHAT_BUSY` | 정의된 코드, 현재 동시 요청 차단 미구현 |
| 422 | `INVALID_INPUT` | 본문·경로·쿼리 검증 실패 |
| 500 | `DB_ERROR` | DB 처리 실패 |
| 500 | `INTERNAL_ERROR` | 처리하지 못한 예외 |
| 502 | `AI_UNAVAILABLE` | 연결·상태·응답 형식 문제, 답변 생성 실패 |
| 503 | `AI_CONFIGURATION_ERROR` | AI 인증·권한·모델 등 설정 문제 |
| 503 | `AUTH_CONFIGURATION_ERROR` | JWT 설정 문제 |
| 504 | `AI_TIMEOUT` | AI 호출 제한 시간 초과 |
| 기타 | `HTTP_ERROR` | 기타 HTTP 오류 |

AI 오류가 발생하면 저장된 질문은 failed로 전환됩니다. 실패 결과 저장 자체가 실패하면 DB 오류가 반환될 수 있습니다. 세부 대응은 [OPERATIONS](OPERATIONS.md)를 참고합니다.
