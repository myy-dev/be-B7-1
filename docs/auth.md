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
발급하지 않습니다. 로그인·JWT 발급은 후속 구현이며 관리자 회원 조회는 아직 mock
저장소를 사용합니다.

테스트는 임시 SQLite DB를 사용해 개발 DB를 수정하지 않습니다.

```bash
uv run --with pytest pytest
```
