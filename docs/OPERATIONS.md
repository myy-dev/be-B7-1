# 백엔드 운영과 Railway 배포

백엔드는 Railway에서 FastAPI를 실행하고 SQLite와 JSONL 이벤트 로그를 영속 볼륨에 저장합니다.

## 환경 변수

로컬은 루트 `.env`, 운영은 Railway Variables에 설정합니다. 변경 후 서버를 재시작하거나 재배포합니다.

| 이름 | 기본값 또는 예시 | 용도와 검증 |
| --- | --- | --- |
| `OPENAI_API_KEY` | 기본값 없음 | 서버 전용 AI API 키. 빈 값 금지 |
| `OPENAI_MODEL` | `gpt-6-luna` | 코드 기본 모델 ID. 빈 값 금지. 운영 계정에서 사용 가능한 ID로 지정 |
| `AI_TIMEOUT_SECONDS` | `30` | 재시도·대기를 포함한 전체 AI 처리 제한 시간. 양의 유한 초 값 |
| `AI_MAX_RETRIES` | `4` | 최초 호출을 제외한 최대 재시도 횟수. 0 이상 정수. 0이면 재시도 비활성화 |
| `JWT_SECRET_KEY` | 기본값 없음 | HS256 서명 키. 최소 32자. `openssl rand -hex 32`로 생성 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | 액세스 토큰 유효 시간. 1~1440분 |
| `DATABASE_URL` | 저장소 루트의 `app.db` 절대 경로 | `sqlite+aiosqlite` URL. 빈 값 금지. Railway 예시: `sqlite+aiosqlite:////data/app.db` |
| `SYSTEM_LOG_PATH` | `logs/system.jsonl` | 이벤트 파일 경로. Railway 예시: `/data/logs/system.jsonl` |
| `CORS_ORIGINS` | 코드에는 로컬 2개와 배포 프론트 2개 등록 | 쉼표로 구분한 실제 프론트 Origin. 환경 변수로 지정하면 기본 목록을 대체 |
| `PORT` | Railway 제공 | 플랫폼이 지정한 서버 포트. 시작 명령에서 사용 |

로컬 예시의 빈 비밀값은 발급·생성해 채웁니다. `.env.example`에 없는 선택 설정도 `.env`에 추가할 수 있습니다.

```dotenv
OPENAI_API_KEY=
OPENAI_MODEL=gpt-6-luna
AI_TIMEOUT_SECONDS=30
AI_MAX_RETRIES=4
JWT_SECRET_KEY=
ACCESS_TOKEN_EXPIRE_MINUTES=30
DATABASE_URL=sqlite+aiosqlite:///./app.db
SYSTEM_LOG_PATH=logs/system.jsonl
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,https://www.quackquack-e.duckdns.org,https://b7-1-two.vercel.app
```

모델 사용 권한은 실제 AI 호출로 확인합니다. `/health`는 DB 연결만 검사하며 AI 키·모델 권한·답변 생성을 검사하지 않습니다. 필수값 누락·길이 오류 등 설정 검증 실패는 서버 시작을 막을 수 있습니다.

## Railway 배포

### 저장소와 빌드 연결

1. Railway에 GitHub 저장소 `myy-dev/be-B7-1`을 연결하고 최신 `main` 커밋을 선택합니다.
2. Root Directory는 `app/` 대신 저장소 루트로 지정합니다.
3. Railpack이 루트의 `pyproject.toml`·`uv.lock`으로 Python·uv 의존성을 설치합니다. 필요하면 Variables에 `RAILPACK_PYTHON_VERSION=3.12`를 지정합니다.
4. Settings의 시작 명령을 지정합니다.

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

앱 경로는 `app.main:app`이며 셸이 `$PORT`를 확장합니다. 배포에서는 `--reload`를 사용하지 않습니다. [시작 명령](https://docs.railway.com/deployments/start-command) · [Railpack Python](https://railpack.com/languages/python)

### 영속 볼륨과 Variables

1. 서비스에 볼륨을 연결하고 Mount Path를 `/data`로 지정합니다.
2. Variables에 실제 `OPENAI_API_KEY`·`JWT_SECRET_KEY`·`OPENAI_MODEL`을 입력합니다.
3. DB·로그 경로와 운영 설정을 등록합니다.

```dotenv
DATABASE_URL=sqlite+aiosqlite:////data/app.db
SYSTEM_LOG_PATH=/data/logs/system.jsonl
AI_TIMEOUT_SECONDS=30
AI_MAX_RETRIES=4
ACCESS_TOKEN_EXPIRE_MINUTES=30
CORS_ORIGINS=https://www.quackquack-e.duckdns.org,https://b7-1-two.vercel.app
```

SQLite 절대 경로는 슬래시 4개를 사용합니다. `/data`의 볼륨 연결·쓰기 권한을 확인하고 단일 서비스 인스턴스로 운영합니다. 앱 시작 때 없는 테이블과 로그 디렉터리를 생성합니다.

볼륨은 실행 중에만 마운트되므로 빌드 중 DB를 초기화하지 않습니다. 볼륨 없는 DB·로그는 배포 교체 시 사라질 수 있습니다. [Railway 볼륨](https://docs.railway.com/volumes)

### 공개 주소와 배포 확인

1. Settings의 Healthcheck Path를 `/health`로 지정합니다.
2. Networking → Generate Domain으로 HTTPS 주소를 생성하거나 기존 주소를 사용합니다.
3. 재배포 후 빌드·실행 로그와 공개 `/health`의 200·`{"status":"ok"}`를 확인합니다.
4. 프론트 `VITE_API_BASE_URL`을 백엔드 Origin으로 설정하고, 백엔드 CORS에 프론트 Origin을 허용합니다. [프론트 설정](https://github.com/myy-dev/fe-B7-1#readme) 참고.
5. 아래 운영 검증을 수행하고 재배포 후 같은 회원·채팅 기록을 재조회합니다.

[Railway FastAPI 가이드](https://docs.railway.com/guides/fastapi) · [DB 전환 시 드라이버·초기화 변경](DATABASE.md)

## 초기 관리자 생성

초기 관리자는 시드 스크립트로 생성합니다. Railway CLI 설치 후 배포 프로젝트·환경·백엔드 서비스에 연결합니다.

```bash
railway login
railway link
railway ssh
```

컨테이너의 저장소 루트에서 실행합니다. 서비스와 같은 `DATABASE_URL`·볼륨을 사용하며 로컬 실행은 로컬 DB에만 생성합니다. 비밀번호는 명령 인자 대신 프롬프트로 입력합니다.

```bash
python scripts/seed_admin.py --username admin --name 관리자
```

비밀번호는 8자 이상이며 기존 관리자가 있으면 추가 생성하지 않습니다. 프롬프트 사용이 불가능하면 Variables에 시드 전용 `SEED_ADMIN_PASSWORD`를 임시 설정하고 실행 후 즉시 제거합니다.

로그인 후 `/api/v1/auth/me`의 `role=admin`·관리자 조회 200을 확인합니다. 다른 회원은 역할 변경 API로 승격합니다. 비밀번호 변경 API는 없으므로 관리 가능한 비밀번호를 정합니다. [Railway SSH](https://docs.railway.com/cli/ssh)

## 서버 로그와 요청 추적

Uvicorn 실행·접근 로그와 앱 이벤트를 확인합니다. 이벤트는 스트림과 `SYSTEM_LOG_PATH`의 JSONL 파일에 기록됩니다. 아래 로컬 경로는 Railway에서 `/data/logs/system.jsonl`로 바꿉니다.

```bash
tail -n 50 logs/system.jsonl
```

| 영역 | 이벤트 |
| --- | --- |
| 요청 | `request_received`, `request_completed`, `request_failed` |
| 공통 오류 | `api_error` |
| AI 호출 | `ai_call_started`, `ai_call_succeeded`, `ai_call_failed` |
| DB 저장 | `db_save_succeeded`, `db_save_failed` |
| 회원 | `user_signed_up`, `user_logged_in`, `user_login_failed` |

AI 이벤트는 호출 전체의 시작·최종 결과이며 개별 재시도는 기록하지 않습니다. `request_failed`·`ai_call_failed`·`db_save_failed` 또는 상태 코드 500 이상은 `ERROR`, 그 외 로그인 실패는 `WARNING`, 나머지는 `INFO`입니다.

기본 필드는 `timestamp`(UTC)·`level`·`event`·`request_id`·`user_id`·`method`·`path`·`status_code`입니다. 경로에는 쿼리 문자열을 포함하지 않으며 인증 전 사용자 ID는 null입니다. 파일에는 `chat_id`·`result`·`error_code`·`duration_ms`·`exception_type`도 기록합니다. 질문·답변 원문, 비밀번호, 토큰, API 키와 스택 트레이스는 기록하지 않습니다.

응답의 `X-Request-ID` 또는 오류 본문 `request_id`로 요청을 추적합니다.

```bash
rg -F '응답에서 확인한-request-id' logs/system.jsonl
```

관리자 `/api/v1/admin/system-logs`는 이벤트·레벨·기간으로 유효한 줄을 필터링해 최신순으로 기본 필드를 반환합니다. 파일의 사용자 ID는 문자열, 관리자 응답은 정수입니다. 기존 `http_status`는 `status_code`로 읽으며 두 값이 있으면 새 필드를 우선합니다. 잘못된 JSON·필드·시각은 조회에서 제외하며 원본 파일은 수정하지 않습니다.

파일 쓰기 오류는 stderr에 표시될 수 있고, 시작 시 경로 생성·파일 열기 실패는 앱 시작을 막을 수 있습니다. 권한·디스크를 확인하고 로그 로테이션·보관 기간은 별도 설정합니다.

## 공통 오류 처리

검증·인증·권한·DB·AI 오류는 `error.code`·`error.message`·`error.request_id` JSON을 반환합니다. 입력 원문·내부 검증 상세·비밀값은 제외합니다. 없는 경로·허용하지 않는 메서드도 같은 형식이며 예상하지 못한 서버 오류와 DB 오류는 구분합니다.

요청별 UUID4를 `X-Request-ID`·오류 본문·저장된 질문에 함께 사용합니다. 입력 검증·질문 저장 실패 시 DB 기록은 없을 수 있습니다. JWT 설정 누락·최소 길이 위반은 앱 시작 때 검증합니다.

회원가입·로그인·로그아웃의 일부 실패 응답은 OpenAPI에 등록되어 있지 않습니다. Swagger의 기본 422 설명과 실제 공통 오류 형식이 다를 수 있습니다.

## AI 재시도와 타임아웃

SDK 재시도는 `max_retries=0`이며 `OpenAIClient`가 직접 재시도합니다. 기본 `AI_MAX_RETRIES=4`는 최초 호출 포함 최대 5회입니다. `AI_TIMEOUT_SECONDS=30`은 AI 호출 시작부터 모든 시도·대기를 합한 30초이며 앞뒤 DB 시간은 제외합니다. HTTP 요청·DB 작업을 재전송하지 않습니다.

- 재시도: 연결 오류(SDK 타임아웃 포함)·HTTP 408·409·429·5xx. 전체 시간·횟수 제한 안에서 시도합니다.
- 재시도 제외: `x-should-retry: false`, 인증·권한·모델 찾기 오류, 잘못된 형식·미완료·빈 답변.
- `Retry-After`: 양의 유한 초 값(소수 포함)은 지터 없이 사용합니다. `retry-after-ms`·날짜·잘못된 값(0 이하·NaN·무한대 등)은 사용하지 않고 백오프로 대체합니다.
- 백오프: 1·2·4·8초, 상한 8초에 매번 0.75~1.0배 무작위 지터를 적용합니다.
- 대기가 남은 시간 이상이거나 호출·대기 중 전체 시간을 넘으면 추가 호출 없이 `AI_TIMEOUT`입니다. 비동기 취소 후에도 재시도하지 않습니다.

| 최종 상황 | 응답과 저장 |
| --- | --- |
| 제한 시간 초과·최종 SDK 타임아웃 | `504 AI_TIMEOUT`, 질문 기록 `failed` |
| 인증·권한·모델 찾기 실패 | `503 AI_CONFIGURATION_ERROR`, `failed` |
| 연결·기타 API 상태·JSON 오류·미완료·빈 답변 | `502 AI_UNAVAILABLE`, `failed` |
| 예상하지 못한 AI 예외 | `failed/INTERNAL_ERROR` 저장 후 공통 500 |
| DB 조회·저장 예외 | `500 DB_ERROR`, 롤백·실패 로그. 결과 저장 실패 시 기록이 pending으로 남을 수 있음 |

재시도는 같은 질문·문맥·최초 요청 ID와 기록 한 행을 유지합니다. 클라이언트의 재전송은 새 요청·새 기록입니다. 중단된 `pending` 자동 복구·요청 멱등성·같은 방 동시 질문 차단은 없습니다. `CHAT_BUSY`는 정의만 있고 반환 경로는 없습니다.

## 운영 검증

격리된 로컬 테스트입니다. 실제 AI를 호출하는 외부 검증은 별도로 수행합니다.

```bash
uv run pytest
```

테스트 계정·채팅방으로 가입·로그인·질문·기록 조회, 비로그인·타인 기록·관리자 접근 제한, 로그아웃 후 토큰 차단, 삭제 후 원본 보존을 확인합니다. 재시작·재배포 후 같은 기록을 조회하고, AI·DB 실패 시 오류 응답·저장 상태·요청별 로그와 이후 요청 처리를 확인합니다.

## 데이터와 비밀값 관리

AI·JWT 키는 백엔드 `.env` 또는 Railway Variables에 보관합니다. 브라우저에 공개되는 `VITE_` 변수와 README·예시·PR·캡처에 키·비밀번호·토큰을 넣지 않습니다.

`.env`·환경별 비밀 설정·키 파일·DB·로그는 Git에서 제외합니다. 이미 추적된 파일은 `.gitignore`로 제거되지 않으므로 목록을 확인합니다.

```bash
git ls-files .env '.env.*' '*.pem' '*.key' '*.db' '*.sqlite' '*.sqlite3' '*.jsonl'
```

예시 외 비밀 설정·실데이터가 추적되지 않아야 합니다. 노출된 비밀값은 폐기·재발급하고 재발 방지·Git 이력을 처리합니다.

일관된 SQLite 백업과 복원 검증을 수행합니다. WAL 모드에서는 DB 파일만 복사하지 않습니다. 논리 삭제 후에도 대화 원문이 남으므로 보관·물리 삭제 정책은 별도로 정합니다.
