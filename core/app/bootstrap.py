"""Bootstrap контрол-плейна — сев первого оператора в ЧИСТОЙ облачной БД (#15).

Свежий облачный инстанс ядра стартует без пользователей → создать оператора неоткуда (публичного
сам-регистра нет — это дыра). Сеем оператора из env `BOOTSTRAP_OPERATOR_EMAIL`/`_PASSWORD` ОДИН раз
на старте (start.sh, после миграций). Идемпотентно: оператор с таким email есть → no-op.
Пароль из env (секрет-стор Railway), в лог НЕ печатаем. Go-live — TOTP оператора (заготовка).
"""

import os

from sqlalchemy import select

from app.db import get_sessionmaker
from app.models import User
from app.security import hash_password


def seed_operator() -> None:
    email = os.environ.get("BOOTSTRAP_OPERATOR_EMAIL")
    password = os.environ.get("BOOTSTRAP_OPERATOR_PASSWORD")
    if not email or not password:
        print("[bootstrap] BOOTSTRAP_OPERATOR_* не заданы — пропуск сева оператора")
        return
    sm = get_sessionmaker()
    with sm() as session:
        existing = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if existing is not None:
            print(f"[bootstrap] оператор {email} уже есть — no-op")
            return
        session.add(User(email=email, role="operator", password_hash=hash_password(password)))
        session.commit()
        print(f"[bootstrap] оператор {email} создан (роль operator)")


if __name__ == "__main__":
    seed_operator()
