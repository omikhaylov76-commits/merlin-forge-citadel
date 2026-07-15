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
from app.models import ApiToken, Client, ExchangeAccount, Instance, User
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
            # Пароль — из env (источник истины бутстрапа): синхронизируем при КАЖДОМ деплое
            # (Оператор меняет пароль через env + передеплой; UI смены нет). В лог не пишем.
            existing.password_hash = hash_password(password)
            session.commit()
            print(f"[bootstrap] оператор {email} есть — пароль синхронизирован из env")
            return
        session.add(User(email=email, role="operator", password_hash=hash_password(password)))
        session.commit()
        print(f"[bootstrap] оператор {email} создан (роль operator)")


def seed_orchestrator() -> None:
    """Сев токена принципала `orchestrator` (шов S3, ADR-0009) — чтобы оркестратор арендовал
    deploy-jobs у облачного ядра. Токен из env BOOTSTRAP_ORCHESTRATOR_TOKEN (то же значение — в
    orchestrator/.env). Машинный токен, не протухает (ADR-0008v2). Идемпотентно по хэшу.
    """
    tok = os.environ.get("BOOTSTRAP_ORCHESTRATOR_TOKEN")
    if not tok:
        print("[bootstrap] BOOTSTRAP_ORCHESTRATOR_TOKEN не задан — пропуск orchestrator-токена")
        return
    sm = get_sessionmaker()
    with sm() as session:
        h = hash_token(tok)
        if session.execute(
            select(ApiToken).where(ApiToken.token_sha256 == h)
        ).scalar_one_or_none() is not None:
            print("[bootstrap] orchestrator-токен уже есть — no-op")
            return
        session.add(ApiToken(
            token_sha256=h, principal="orchestrator", subject_id="orchestrator",
            scope="orchestrator", expires_at=None,
        ))
        session.commit()
        print("[bootstrap] orchestrator-токен посеян")


def seed_demo_instance() -> None:
    """Демо-инстанс + его родители (client + exchange_account для FK Ф3) + instance-токен из env.
    Токен задаём МЫ (env-стор), core хранит SHA-256; картридж юзает сырой как MF_INSTANCE_TOKEN.
    ДЕМО-обход: боевой путь — create_instance→оркестратор. Идемпотентно по instance id.
    client/account id — из env (BOOTSTRAP_CLIENT_ID/ACCOUNT_ID) либо генерятся консистентно.

    У существующего облачного демо-инстанса (до Ф3) родители — плейсхолдеры из бэкофилла 0005;
    свежий деплой заводит нормальных родителей."""
    iid = os.environ.get("BOOTSTRAP_INSTANCE_ID")
    tok = os.environ.get("BOOTSTRAP_INSTANCE_TOKEN")
    if not iid or not tok:
        print("[bootstrap] BOOTSTRAP_INSTANCE_* не заданы — пропуск демо-инстанса")
        return
    client_id = uuid.UUID(os.environ.get("BOOTSTRAP_CLIENT_ID", str(uuid.uuid4())))
    account_id = uuid.UUID(os.environ.get("BOOTSTRAP_ACCOUNT_ID", str(uuid.uuid4())))
    sm = get_sessionmaker()
    with sm() as session:
        if session.get(Instance, uuid.UUID(iid)) is not None:
            print(f"[bootstrap] демо-инстанс {iid} уже есть — no-op")
            return
        # Родители ДО инстанса (FK client_id/account_id, Ф3). Идемпотентно по id.
        if session.get(Client, client_id) is None:
            session.add(Client(id=client_id, name="demo client", is_active=True))
        if session.get(ExchangeAccount, account_id) is None:
            session.add(ExchangeAccount(
                id=account_id, client_id=client_id, exchange="bybit",
                label="demo (api-demo.bybit.com)", is_active=True,
            ))
        session.flush()  # родители материализованы до инстанса
        session.add(Instance(
            id=uuid.UUID(iid), client_id=client_id, account_id=account_id,
            bot_type_id=uuid.uuid4(), profile_id=uuid.uuid4(), status="running", health="ok",
        ))
        session.add(ApiToken(
            token_sha256=hash_token(tok), principal="instance", subject_id=iid,
            scope="instance", expires_at=None,  # машинный токен (не протухает, ADR-0008v2)
        ))
        session.commit()
        print(f"[bootstrap] демо-инстанс {iid} (+client/account) + instance-токен посеяны")


if __name__ == "__main__":
    seed_operator()
    seed_orchestrator()
    seed_demo_instance()
