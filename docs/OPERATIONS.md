# 운영·배포 안내

## 환경 변수

`.env.example`을 복사해 실제 값을 채웁니다. 앱은 프로젝트 루트 실행을 기준으로 `.env`를 읽습니다. 운영 환경에서는 동일 이름의 환경 변수를 주입할 수도 있습니다.

| 이름 | 예시·기본값 | 용도·검증 |
| --- | --- | --- |
| `OPENAI_API_KEY` | 예시 파일은 빈 값 | 필수, 비어 있으면 앱 설정 검증 실패 |
| `OPENAI_MODEL` | `gpt-6-luna` | 코드 기본값, 사용할 모델 ID; 빈 값 금지 |
| `AI_TIMEOUT_SECONDS` | `30` | 양의 유한 초 값 |
| `JWT_SECRET_KEY` | 예시 파일은 빈 값 | 최소 32자; `openssl rand -hex 32`로 생성 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | 1~1440분 |
| `DATABASE_URL` | `sqlite+aiosqlite:///./app.db` | 비동기 SQLite URL; 코드 기본값은 저장소 루트 절대 경로 |
| `SYSTEM_LOG_PATH` | `logs/system.jsonl` | 이벤트 로그 파일 경로 |
| `CORS_ORIGINS` | 로컬 프론트 주소 2개 | 쉼표로 구분한 허용 프론트 오리진 |

예시 모델은 코드 기본값을 옮긴 것입니다. 운영 계정에서 해당 모델을 사용할 수 있는지 실제 호출로 확인합니다. JWT 설정 문제는 인증 API에서 `503 AUTH_CONFIGURATION_ERROR`로 나타날 수 있습니다. `/health`는 AI 키·모델이나 JWT 설정을 검사하지 않습니다.

## 배포 절차

1. Python 3.12 이상과 uv를 준비하고 배포할 커밋을 체크아웃합니다.
2. `uv sync --locked`로 의존성을 설치합니다.
3. 비밀값을 주입하고 DB·로그의 영속 저장 경로와 쓰기 권한을 확인합니다. 운영 `CORS_ORIGINS`에 실제 프론트 주소를 지정합니다.
4. 서버를 실행하고 프로세스 관리 도구로 재시작 정책을 구성합니다.

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

5. 외부 공개 시 HTTPS와 리버스 프록시를 구성합니다. 프록시 응답 제한은 AI 제한 시간과 DB 처리 시간을 고려합니다.
6. 아래 운영 검증을 수행합니다.

저장소에는 Docker·CI 배포·서비스 관리자 설정이 없습니다. 구체적인 호스팅 제공자와 운영 인프라는 확인되지 않았습니다. SQLite 외의 DB는 현재 연결 초기화 코드를 수정해야 합니다.

## 서버 로그

Uvicorn의 실행·접근 로그와 앱 이벤트 로그를 함께 확인합니다. 앱 이벤트는 스트림과 `SYSTEM_LOG_PATH`의 JSONL 파일에 기록됩니다.

```bash
tail -n 50 logs/system.jsonl
```

이벤트는 `request_received`, `request_completed`, `request_failed`, `api_error`, `ai_call_started`, `ai_call_succeeded`, `ai_call_failed`, `db_save_succeeded`, `db_save_failed`입니다. `request_id`, `user_id`, `chat_id`, `result`, `error_code`, `duration_ms`, `http_status`, `exception_type` 등 허용된 메타데이터를 저장합니다. 앱 이벤트 로그에는 질문·답변 원문, 비밀번호, 토큰, API 키와 스택 트레이스를 넣지 않습니다. 대화 원문은 DB에 저장됩니다.

응답 `X-Request-ID` 또는 오류 본문의 `request_id`로 이벤트를 연결합니다. 관리자 `/api/v1/admin/system-logs`에서 레벨·이벤트·기간 필터로 조회할 수 있습니다. 자동 로그 로테이션·보관 기간 정책은 구현되어 있지 않습니다. 운영에서 디스크 용량과 보관 정책을 별도로 관리합니다. [로그 형식](system-logs.md)을 참고합니다.

## AI 타임아웃·예외 처리

| 상황 | 동작·확인 사항 |
| --- | --- |
| 제한 시간 초과 | SDK timeout과 `asyncio.timeout` 사용, `504 AI_TIMEOUT`; 네트워크·지연·설정 확인 |
| 인증·권한·모델 찾기 실패 | `503 AI_CONFIGURATION_ERROR`; 키와 모델 설정 확인 |
| 연결·기타 API 상태·JSON 오류, 미완료·빈 응답 | `502 AI_UNAVAILABLE`; 연결과 AI 서비스 상태 확인 |
| 예상하지 못한 AI 예외 | 질문을 failed/INTERNAL_ERROR로 저장한 뒤 예외 전달, 공통 500 반환 |
| DB 조회·저장 예외 | `500 DB_ERROR`; 쓰기 권한·파일·디스크 확인 |

AI 클라이언트는 자동 재시도를 하지 않습니다. 실패 질문은 기록에 남습니다. 같은 질문을 다시 보내면 새 기록·새 AI 호출이 생깁니다. 프로세스 중단·결과 저장 실패 시 남은 `pending` 기록의 자동 복구와 요청 멱등성은 구현되어 있지 않습니다. 같은 채팅방에 동시에 질문을 보내는 차단 장치도 없습니다.

## 운영 검증

자동 검증:

```bash
uv run pytest
```

수동 검증은 테스트 계정과 분리된 운영 점검용 채팅방으로 수행합니다. 실제 AI 호출에는 사용량이 발생합니다.

| 점검 | 기대 결과 |
| --- | --- |
| `GET /health` | 200, `status=ok`; DB 연결 확인 |
| 회원가입·로그인 | 201·200, 토큰 발급; 잘못된 입력 422, 중복 아이디 409 |
| 토큰 없는 채팅 요청 | 401 |
| 채팅 생성·질문·상세 조회 | 201·201·200, completed 답변 저장 |
| 다른 회원의 채팅방 조회 | 404 |
| 일반 회원의 관리자 조회 | 403 |
| 관리자 조회 | DB role이 admin인 계정으로 200 |
| 로그아웃 후 같은 토큰 재사용 | 로그아웃 204, 재사용 401 |
| 채팅방 삭제 후 사용자 조회 | 삭제 204, 조회 404 |
| 재시작 후 조회 | DB와 로그 파일의 영속성 확인 |
| 실패 경로 | 격리된 테스트에서 타임아웃·AI·DB 예외 및 failed 저장 확인 |

헬스 체크 성공만으로 AI 답변 생성과 권한 검증을 통과했다고 판단하지 않습니다. 현재 테스트 이름과 실제 결과는 실행 시점에 기록합니다.

## 데이터·비밀값 관리

`.env`, 환경별 비밀 설정, 키 파일, 로컬 DB·로그는 Git에서 제외합니다. `.gitignore`는 이미 추적된 파일을 제거하지 않으므로 커밋 전에 추적 상태도 확인합니다.

```bash
git ls-files .env '.env.*' '*.pem' '*.key'
```

출력에 `.env.example`만 있는지 확인합니다. 운영 DB는 일관된 SQLite 백업 방식으로 백업하고 복원 검증을 수행합니다. WAL 모드에서는 DB 파일만 복사하는 방식에 의존하지 않습니다. 채팅방 논리 삭제는 원문 삭제가 아니므로 데이터 보관·물리 삭제 정책은 별도로 정합니다.
