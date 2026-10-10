# AI·채팅 API 명세

## 엔드포인트 목록

| 메서드 | 경로 | 기능 | 성공 코드 |
| --- | --- | --- | --- |
| POST | `/api/v1/chats` | 세션 생성 | 201 |
| GET | `/api/v1/chats` | 내 세션 목록 조회 | 200 |
| GET | `/api/v1/chats/{chat_id}` | 세션 상세 정보 및 대화 기록 조회 | 200 |
| POST | `/api/v1/chats/{chat_id}/messages` | 질문 전송 및 AI 답변 반환 | 201 |
| DELETE | `/api/v1/chats/{chat_id}` | 세션 논리 삭제 | 204 |

---

## 1. 세션 생성

### POST /api/v1/chats

로그인한 사용자 소유의 세션을 생성

### Request Body

없음

사용자 식별자는 서버에서 인증 정보를 통해 확인

### Response Body

`201 Created`

```json
{
  "chat_id": "e6100748-b7f0-48e6-a264-7c20a748cf93",
  "created_at": "2026-10-02T03:00:00Z"
}
```

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| chat_id | string(uuid) | 생성된 세션 식별자 |
| created_at | string(date-time) | 세션 생성 시각 |

### Status Codes

| 코드 | 설명 |
| --- | --- |
| 201 | 세션 생성 성공 |
| 401 | 인증 실패 |
| 500 | 서버 처리 실패 |

---

## 2. 세션 목록 조회

### GET /api/v1/chats

로그인한 사용자의 삭제되지 않은 모든 세션 조회.

### Request Body

없음.

### Response Body

`200 OK`

```json
{
  "items": [
    {
      "chat_id": "e6100748-b7f0-48e6-a264-7c20a748cf93",
      "created_at": "2026-10-02T03:00:00Z"
    }
  ]
}
```

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| items | array | 세션 목록 |
| items[].chat_id | string(uuid) | 세션 식별자 |
| items[].created_at | string(date-time) | 세션 생성 시각 |

- 생성 시각 내림차순으로 반환
- 생성 시각이 같으면 `chat_id` 내림차순으로 정렬
- 세션이 없으면 `{"items": []}`를 반환
- 삭제된 세션은 목록에서 제외하며 삭제된 세션만 남으면 `{"items": []}`를 반환

### Status Codes

| 코드 | 설명 |
| --- | --- |
| 200 | 조회 성공 |
| 401 | 인증 실패 |
| 500 | 서버 처리 실패 |

---

## 3. 세션 상세 조회

### GET /api/v1/chats/{chat_id}

특정 세션 정보와 전체 대화 기록을 함께 조회

### Path Parameters

| 이름 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| chat_id | string(uuid) | O | 조회할 세션 식별자 |

### Request Body

없음.

### Response Body

`200 OK`

```json
{
  "chat_id": "e6100748-b7f0-48e6-a264-7c20a748cf93",
  "created_at": "2026-10-02T03:00:00Z",
  "messages": [
    {
      "request_id": "16fd2706-8baf-433b-82eb-8c7fada847da",
      "chat_id": "e6100748-b7f0-48e6-a264-7c20a748cf93",
      "question": "FastAPI가 뭐야?",
      "answer": "Python으로 웹 API를 만드는 프레임워크입니다.",
      "status": "completed",
      "error_code": null,
      "created_at": "2026-10-02T03:00:05Z",
      "finished_at": "2026-10-02T03:00:07Z"
    }
  ]
}
```

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| chat_id | string(uuid) | 세션 식별자 |
| created_at | string(date-time) | 세션 생성 시각 |
| messages | array | 대화 기록 목록. 각 항목은 아래의 공통 대화 기록 스키마를 사용 |

- `messages`의 항목 하나는 질문 1개와 답변 최대 1개로 구성된다.
- 대화 기록은 생성 시각 오름차순으로 반환한다.
- 처리 중·성공·실패 기록을 모두 포함한다.
- 대화 기록이 없으면 `messages: []`를 반환한다.

### Status Codes

| 코드 | 설명 |
| --- | --- |
| 200 | 조회 성공 |
| 401 | 인증 실패 |
| 404 | 세션이 없거나 본인 소유가 아니거나 삭제됨 |
| 422 | UUID 형식 오류 |
| 500 | 서버 처리 실패 |

---

## 4. 질문 전송

### POST /api/v1/chats/{chat_id}/messages

세션에서 질문을 전송하고 AI 응답 수신

### Path Parameters

| 이름 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| chat_id | string(uuid) | O | 질문을 보낼 세션 식별자 |

### Request Body

```json
{
  "question": "FastAPI가 뭐야?"
}
```

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| question | string | O | 앞뒤 공백 제거 후 1~1,000자의 질문 |

- 길이는 Python 문자열의 `len()` 기준인 Unicode 코드 포인트 수로 계산한다. 내부 공백·줄바꿈을 포함하며 별도 Unicode 정규화는 수행하지 않는다. 조합 이모지는 화면상 한 글자여도 여러 글자로 계산될 수 있다.
- 빈 문자열·공백만 있는 문자열·앞뒤 공백 제거 후 1,000자를 초과하는 문자열은 `422 INVALID_INPUT`으로 거절한다. 이 경우 대화 기록 생성과 AI 호출을 수행하지 않는다.
- 질문 길이 초과 시 `error.message`는 "질문은 1,000자를 초과할 수 없습니다."다. 빈 입력·공백만 있는 입력·잘못된 타입·UUID 형식 등 다른 검증 오류는 기존 "입력값을 확인해 주세요."를 반환한다. 오류 코드와 응답 필드는 유지하고 입력 원문·내부 검증 상세는 포함하지 않는다.

### Response Body

`201 Created`

```json
{
  "request_id": "16fd2706-8baf-433b-82eb-8c7fada847da",
  "chat_id": "e6100748-b7f0-48e6-a264-7c20a748cf93",
  "question": "FastAPI가 뭐야?",
  "answer": "Python으로 웹 API를 만드는 프레임워크입니다.",
  "status": "completed",
  "error_code": null,
  "created_at": "2026-10-02T03:00:05Z",
  "finished_at": "2026-10-02T03:00:07Z"
}
```

- 질문·답변 한 건을 단일 객체로 반환
- 공통 대화 기록 스키마를 사용
- 성공 응답의 `status`는 항상 `completed`
- 질문·답변 저장이 완료된 후 성공 응답을 반환
- 실패 시에는 공통 오류 응답을 반환
- 삭제된 세션에 새 질문을 보내면 `404 CHAT_NOT_FOUND`를 반환하며 질문 저장·AI 호출을 수행하지 않는다.
- 삭제 전 소유권·삭제 여부 검사를 통과한 질문은 세션이 삭제되어도 기존 대화 기록에 결과를 저장하고 원래 요청에 응답한다. 성공하면 `201`, 실패하면 기존 공통 오류 응답을 반환한다.

### Status Codes

| 코드 | 설명 |
| --- | --- |
| 201 | 질문·답변 저장 및 반환 성공 |
| 401 | 인증 실패 |
| 404 | 세션이 없거나 본인 소유가 아니거나 삭제됨 |
| 409 | 해당 세션의 이전 질문이 처리 중 |
| 422 | 질문 입력 또는 UUID 형식 오류 |
| 5xx | 서버 또는 AI 처리 실패 |

---

## 5. 세션 삭제

### DELETE /api/v1/chats/{chat_id}

로그인한 사용자 소유의 세션을 논리 삭제한다. 채팅방과 대화 기록은 DB에 유지한다.

### Path Parameters

| 이름 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| chat_id | string(uuid) | O | 삭제할 세션 식별자 |

### Request Body

없음. 사용자 식별자는 서버에서 인증 정보를 통해 확인한다.

### Response Body

`204 No Content`

본문 없음. 삭제 시각 저장을 완료한 뒤 반환한다.

### 삭제 정책

- 세션의 `deleted_at`에 UTC 삭제 시각을 기록한다. 별도 `is_deleted`나 대화 기록의 삭제 상태는 추가하지 않는다.
- 삭제된 세션은 사용자 목록에서 제외하며 상세 조회·새 질문 전송·재삭제는 `404 CHAT_NOT_FOUND`를 반환한다.
- `deleted_at`은 내부 저장 필드이며 기존 세션·대화 기록 응답 필드는 유지한다.
- AI 답변 생성 중이거나 `pending` 기록이 남아 있어도 삭제를 허용한다. 삭제 API는 처리 중이라는 이유로 `409 CHAT_BUSY`를 반환하지 않는다.
- 삭제 전 소유권·삭제 여부 검사를 통과한 질문은 AI 호출을 취소하지 않고 완료·실패 결과를 기존 대화 기록에 저장한 뒤 원래 요청에 응답한다. 삭제가 해당 요청의 기존 성공·오류 처리 규칙을 변경하거나 세션을 복구하지 않는다.
- 프론트엔드는 삭제된 세션의 늦은 질문 응답을 화면에 표시하거나 해당 세션을 목록에 다시 추가하지 않는다.

### Status Codes

| 코드 | 설명 |
| --- | --- |
| 204 | 세션 논리 삭제 성공. 응답 본문 없음 |
| 401 | 인증 실패 |
| 404 | 세션이 없거나 본인 소유가 아니거나 이미 삭제됨 (`CHAT_NOT_FOUND`) |
| 422 | UUID 형식 오류 (`INVALID_INPUT`) |
| 500 | DB 조회·저장 실패 (`DB_ERROR`) 또는 예상하지 못한 서버 예외 (`INTERNAL_ERROR`) |

---

## 공통 대화 기록 스키마

세션 상세 응답의 `messages[]`와 질문 전송 응답에서 사용

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| request_id | string(uuid) | 최초 질문 요청 및 대화 기록 식별자 |
| chat_id | string(uuid) | 소속 세션 식별자 |
| question | string | 앞뒤 공백이 제거된 질문 |
| answer | string 또는 null | 완성된 AI 답변 |
| status | string | `pending`, `completed`, `failed` 중 하나 |
| error_code | string 또는 null | 실패 원인 코드 |
| created_at | string(date-time) | 질문 기록 생성 시각 |
| finished_at | string(date-time) 또는 null | 성공 또는 실패 처리 완료 시각 |

모든 필드는 응답에 포함하며, 값이 없는 필드는 아래 기준에 따라 `null`로 반환한다.

| status | answer | error_code | finished_at |
| --- | --- | --- | --- |
| pending | null | null | null |
| completed | 답변 문자열 | null | 완료 시각 |
| failed | null | 오류 코드 | 실패 시각 |

저장된 기록의 `request_id`는 최초 질문 요청의 값으로 유지한다. 이후 세션을 다시 조회해도 변경되지 않는다.

---

## 오류 응답

인증 실패, 입력 검증 오류, 서버 처리 오류는 동일한 응답 구조를 사용

### Response Body

예시: AI 호출 타임아웃

```json
{
  "error": {
    "code": "AI_TIMEOUT",
    "message": "응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
    "request_id": "16fd2706-8baf-433b-82eb-8c7fada847da"
  }
}
```

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| error.code | string | 오류 구분 코드 |
| error.message | string | 사용자 안내 문구 |
| error.request_id | string(uuid) | 오류가 발생한 현재 요청의 식별자 |

### 오류 코드

| HTTP 상태 | error.code | 설명 |
| --- | --- | --- |
| 401 | UNAUTHORIZED | 인증 실패 |
| 404 | CHAT_NOT_FOUND | 세션이 없거나 본인 소유가 아니거나 삭제됨 |
| 409 | CHAT_BUSY | 질문 전송 시 해당 세션의 이전 질문이 처리 중. 세션 삭제에는 적용하지 않음 |
| 422 | INVALID_INPUT | 요청 입력값 오류 |
| 500 | DB_ERROR | DB 조회·저장 실패 |
| 502 | AI_UNAVAILABLE | AI 연결·응답 실패 |
| 503 | AI_CONFIGURATION_ERROR | AI 관련 서버 설정 오류 |
| 504 | AI_TIMEOUT | AI 호출 타임아웃 |


### 일반 HTTP·서버 오류

최신 main의 공통 오류 처리를 모든 API에 적용한다. 위 채팅 API 오류 코드와 함께 다음 코드를 사용한다.

| HTTP 상태 | error.code | 설명 |
| --- | --- | --- |
| 404 | NOT_FOUND | 등록되지 않은 API 경로 |
| 405 | METHOD_NOT_ALLOWED | 해당 경로가 지원하지 않는 HTTP 메서드 |
| 기타 HTTP 오류 | HTTP_ERROR | 위 코드 또는 채팅 오류 코드로 처리하지 않는 일반 HTTP 오류 |
| 500 | INTERNAL_ERROR | DB 오류로 분류하지 않는 예상하지 못한 서버 예외 |

동일한 공통 오류 응답 구조를 사용하며, `request_id`는 응답의 `X-Request-ID`와 일치한다. 채팅방이 없거나 본인 소유가 아니거나 삭제된 경우에는 `CHAT_NOT_FOUND`를 반환한다.
