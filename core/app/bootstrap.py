"""Bootstrap контрол-плейна — сев первого оператора в ЧИСТОЙ облачной БД (#15).

Свежий облачный инстанс ядра стартует без пользователей → создать оператора неоткуда (публичного
сам-регистра нет — это дыра). Сеем оператора из env `BOOTSTRAP_OPERATOR_EMAIL`/`_PASSWORD` ОДИН раз
на старте (start.sh, после миграций). Идемпотентно: оператор с таким email есть → no-op.
Пароль из env (секрет-стор Railway), в лог НЕ печатаем. Go-live — TOTP оператора (заготовка).
"""

import os
import uuid

from sqlalchemy import select

from app.db import get_sessionmaker
from app.models import ApiToken, Instance, User
from app.security import hash_password, hash_token


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


def seed_demo_instance() -> None:
    """Демо-инстанс + instance-токен из env (сквозняк облако-в-облако). Токен задаём МЫ (env-стор),
    core хранит его SHA-256 — картридж юзает сырой как MF_INSTANCE_TOKEN. ДЕМО-обход: боевой путь
    инстанса — через create_instance→оркестратор (токен в job). Идемпотентно по instance id."""
    iid = os.environ.get("BOOTSTRAP_INSTANCE_ID")
    tok = os.environ.get("BOOTSTRAP_INSTANCE_TOKEN")
    if not iid or not tok:
        print("[bootstrap] BOOTSTRAP_INSTANCE_* не заданы — пропуск демо-инстанса")
        return
    sm = get_sessionmaker()
    with sm() as session:
        if session.get(Instance, uuid.UUID(iid)) is not None:
            print(f"[bootstrap] демо-инстанс {iid} уже есть — no-op")
            return
        session.add(Instance(
            id=uuid.UUID(iid), client_id=uuid.uuid4(), account_id=uuid.uuid4(),
            bot_type_id=uuid.uuid4(), profile_id=uuid.uuid4(), status="running", health="ok",
        ))
        session.add(ApiToken(
            token_sha256=hash_token(tok), principal="instance", subject_id=iid,
            scope="instance", expires_at=None,  # машинный токен (не протухает, ADR-0008v2)
        ))
        session.commit()
        print(f"[bootstrap] демо-инстанс {iid} + instance-токен посеяны")


if __name__ == "__main__":
    seed_operator()
    seed_demo_instance()
