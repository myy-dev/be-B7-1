from pwdlib import PasswordHash
from starlette.concurrency import run_in_threadpool

password_hash = PasswordHash.recommended()


async def hash_password(password: str) -> str:
    # CPU 작업을 별도 스레드에서 실행해 다른 요청의 이벤트 루프를 막지 않는다.
    return await run_in_threadpool(password_hash.hash, password)
