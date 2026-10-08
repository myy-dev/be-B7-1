# 회원가입 API

`POST /api/v1/auth/signup` — 인증 없이 일반 회원을 생성합니다.

```json
{
  "username": "Test_User",
  "password": "my-secure-password",
  "name": "홍길동"
}
```

| 필드 | 규칙 |
| --- | --- |
| username | 영문·숫자·밑줄 4~20자. 소문자로 저장하며 대소문자를 구분하지 않고 중복 검사. 공백은 허용하지 않음 |
| password | 8~128자. 공백을 포함해 원문 그대로 해시 처리 |
| name | 앞뒤 공백 제거 후 1~50자 |

세 필드는 필수이며 추가 필드(예: `role`)는 거절합니다. 비밀번호 확인은 프론트에서 처리합니다.

성공 응답: `201 Created`

```json
{
  "id": 1,
  "username": "test_user",
  "name": "홍길동",
  "created_at": "2026-10-06T10:00:00Z"
}
```

| 상태 | error.code | 의미 |
| --- | --- | --- |
| 409 | USERNAME_TAKEN | 이미 사용 중인 아이디. 동시 가입 충돌도 동일하게 처리 |
| 422 | INVALID_INPUT | 필수 값 누락, 입력 규칙 위반 또는 추가 필드 |

```json
{
  "error": {
    "code": "USERNAME_TAKEN",
    "message": "이미 사용 중인 아이디입니다.",
    "request_id": "요청 식별자"
  }
}
```

회원은 SQLite `users` 테이블에 저장되고 권한은 서버에서 `user`로 지정합니다.
비밀번호는 [pwdlib의 권장 Argon2 해시](https://frankie567.github.io/pwdlib/)를
사용하며 응답에 비밀번호나 해시를 포함하지 않습니다.
앱 시작 시 테이블을 생성하므로 별도 SQL 실행은 필요하지 않습니다.

가입 완료 후 프론트는 로그인 화면으로 이동합니다. 이 API는 로그인하거나 토큰을
발급하지 않습니다. 관리자 권한 검사는 JWT 서명 검증과 DB `role` 조회로 동작하며,
무토큰은 `401 UNAUTHORIZED`, 일반 사용자는 `403 FORBIDDEN`을 반환합니다.

테스트는 임시 SQLite DB를 사용해 개발 DB를 수정하지 않습니다.

```bash
uv run --with pytest pytest
```

## 로그인 API

`POST /api/v1/auth/login`

```json
{"username": "Test_User", "password": "my-secure-password"}
```

성공 시 `200 OK`:

```json
{"access_token": "JWT 문자열", "token_type": "bearer", "expires_in": 1800}
```

아이디는 대소문자를 구분하지 않으며 비밀번호 공백은 그대로 비교합니다.
없는 아이디와 잘못된 비밀번호는 동일한 `401 INVALID_CREDENTIALS`를 반환합니다.
입력 규칙 위반은 `422 INVALID_INPUT`입니다. 성공 시 `last_login_at`을 갱신합니다.

`.env`에 `JWT_SECRET_KEY`를 설정하세요. `openssl rand -hex 32`로 생성한
무작위 키를 사용하며 최소 32자가 필요합니다. 설정이 없거나 잘못되면 로그인은
`503 AUTH_CONFIGURATION_ERROR`를 반환합니다. 토큰 만료 시간은
`ACCESS_TOKEN_EXPIRE_MINUTES`(기본 30분)입니다.

채팅 API 요청에는 `Authorization: Bearer <access_token>`을 전달하세요.
Swagger의 Authorize에도 발급된 토큰을 입력할 수 있습니다.
토큰 누락·만료·위조 또는 삭제된 회원은 `401 UNAUTHORIZED`를 반환합니다.
토큰은 HS256 서명과 필수 sub/iat/exp를 검증합니다
([PyJWT 문서](https://pyjwt.readthedocs.io/en/latest/usage.html)).
갱신 토큰과 서버 로그아웃은 제공하지 않으며 만료 후 다시 로그인합니다.
