"""초기 관리자 시드 스크립트.

서버 안에서 1회 실행한다. 같은 DB(/data 마운트)를 직접 열므로
환경변수·볼륨 설정이 앱과 같아야 한다.

    SEED_ADMIN_PASSWORD='초기비번' python scripts/seed_admin.py --username admin

이미 admin 역할이 있으면 종료한다(멱등). 비밀번호는 환경변수
SEED_ADMIN_PASSWORD에서 읽고, 없으면 프롬프트로 입력받는다.
셸 히스토리·Git에 남지 않게 인자로 받지 않는다. 실행 후 로그인해
비밀번호를 바꾼다.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.database import async_session_maker, create_db_and_tables  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.user import User  # noqa: E402
from app.repositories.user_repository import UserRepository  # noqa: E402


async def seed(username: str, name: str, password: str) -> int:
    await create_db_and_tables()
    async with async_session_maker() as session:
        users = UserRepository(session)
        existing = await session.scalar(
            select(User).where(User.role == "admin").limit(1)
        )
        if existing is not None:
            print(f"admin already exists: {existing.username} (id={existing.id})")
            return 0
        if await users.get_by_username(username) is not None:
            print(f"username taken: {username}")
            return 1
        user = User(
            username=username,
            password_hash=await hash_password(password),
            name=name,
            role="admin",
        )
        session.add(user)
        await session.commit()
        print(f"admin seeded: {username} (id={user.id})")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="초기 관리자 1명을 만든다.")
    parser.add_argument("--username", required=True)
    parser.add_argument("--name", default="관리자")
    args = parser.parse_args()
    password = os.environ.get("SEED_ADMIN_PASSWORD") or getpass.getpass(
        "초기 비밀번호: "
    )
    if len(password) < 8:
        print("비밀번호는 8자 이상이어야 합니다.")
        return 1
    return asyncio.run(seed(args.username, args.name, password))


if __name__ == "__main__":
    raise SystemExit(main())
