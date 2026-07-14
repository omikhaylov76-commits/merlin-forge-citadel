"""Гвозди на CRM-схему Ф3 (миграция 0005): таблицы clients/exchange_accounts, активные FK у
instances, CHECK-констрейнты, бэкофилл сирот при апгрейде, bootstrap-родители. Нужен Postgres."""

import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.bootstrap import seed_demo_instance
from app.db import get_sessionmaker
from app.models import Client, ExchangeAccount, Instance

_CORE = Path(__file__).resolve().parents[1]


def _cfg() -> Config:
    cfg = Config(str(_CORE / "alembic.ini"))
    cfg.set_main_option("script_location", str(_CORE / "alembic"))
    return cfg


def _clean() -> None:
    sm = get_sessionmaker()
    with sm() as s:
        # дети instances → instances → родители (FK-порядок удаления)
        for t in ("commands", "jobs", "equity_points", "trades", "events"):
            s.execute(text(f"DELETE FROM {t}"))
        s.execute(text("DELETE FROM instances"))
        s.execute(text("DELETE FROM exchange_accounts"))
        s.execute(text("DELETE FROM clients"))
        s.commit()


def test_tables_exist(_migrated) -> None:
    sm = get_sessionmaker()
    with sm() as s:
        # regclass вернёт oid, если таблица есть; иначе бросит — простой факт наличия
        assert s.execute(text("SELECT to_regclass('clients')")).scalar() is not None
        assert s.execute(text("SELECT to_regclass('exchange_accounts')")).scalar() is not None


def test_instance_requires_real_parents(_migrated) -> None:
    # FK Ф3: инстанс со ссылками на несуществующих client/account отвергается БД
    sm = get_sessionmaker()
    with sm() as s:
        s.add(Instance(
            client_id=uuid.uuid4(), account_id=uuid.uuid4(), bot_type_id=uuid.uuid4(),
            profile_id=uuid.uuid4(), status="pending", health="ok",
        ))
        with pytest.raises(IntegrityError):
            s.flush()
        s.rollback()


def test_account_requires_real_client(_migrated) -> None:
    _clean()
    sm = get_sessionmaker()
    with sm() as s:
        s.add(ExchangeAccount(id=uuid.uuid4(), client_id=uuid.uuid4(), exchange="bybit"))
        with pytest.raises(IntegrityError):
            s.flush()
        s.rollback()


def test_fee_pct_check_rejects_out_of_range(_migrated) -> None:
    _clean()
    sm = get_sessionmaker()
    with sm() as s:
        s.add(Client(id=uuid.uuid4(), name="bad fee", fee_pct_default=Decimal("1.5")))  # ≥1 нельзя
        with pytest.raises(IntegrityError):
            s.flush()
        s.rollback()
    with sm() as s:  # валидная доля проходит
        s.add(Client(id=uuid.uuid4(), name="ok fee", fee_pct_default=Decimal("0.2")))
        s.flush()
        s.rollback()


def test_exchange_enum_check(_migrated) -> None:
    _clean()
    sm = get_sessionmaker()
    with sm() as s:
        cid = uuid.uuid4()
        s.add(Client(id=cid, name="c"))
        s.flush()
        s.add(ExchangeAccount(id=uuid.uuid4(), client_id=cid, exchange="kraken"))  # не из allowlist
        with pytest.raises(IntegrityError):
            s.flush()
        s.rollback()


def test_migration_0005_backfills_orphan_instances(_migrated) -> None:
    """Ключ безопасности апгрейда облака: инстанс-сирота (без родителей) при 0004→0005 получает
    плейсхолдеров, FK включается без падения. Downgrade→вставка→upgrade→проверка→откат."""
    cfg = _cfg()
    orphan_c, orphan_a = uuid.uuid4(), uuid.uuid4()
    iid = uuid.uuid4()
    try:
        command.downgrade(cfg, "0004_telemetry_commands")  # снимает FK + роняет clients/accounts
        sm = get_sessionmaker()
        with sm() as s:
            s.execute(
                text(
                    "INSERT INTO instances (id, client_id, account_id, bot_type_id, profile_id, "
                    "status, health) VALUES (:i,:c,:a,:b,:p,'stopped','ok')"
                ),
                {"i": iid, "c": orphan_c, "a": orphan_a, "b": uuid.uuid4(), "p": uuid.uuid4()},
            )
            s.commit()
        command.upgrade(cfg, "0005_crm")  # бэкофилл + включение FK НЕ должны упасть на сироте
        with sm() as s:
            assert s.get(Client, orphan_c) is not None       # плейсхолдер-клиент создан
            assert s.get(ExchangeAccount, orphan_a) is not None  # плейсхолдер-счёт создан
            # FK теперь активен — новый сирота отвергается
            s.add(Instance(
                client_id=uuid.uuid4(), account_id=uuid.uuid4(), bot_type_id=uuid.uuid4(),
                profile_id=uuid.uuid4(), status="pending", health="ok",
            ))
            with pytest.raises(IntegrityError):
                s.flush()
            s.rollback()
    finally:
        command.upgrade(cfg, "head")  # гарантированно вернуть схему на голову
        _clean()  # прибрать тестовые строки (инстанс + плейсхолдеры)


def test_bootstrap_seeds_parents(_migrated, monkeypatch) -> None:
    # bootstrap демо-инстанса заводит client+account (FK держатся на свежем деплое)
    _clean()
    iid = "33333333-3333-3333-3333-333333333333"
    cid = "44444444-4444-4444-4444-444444444444"
    aid = "55555555-5555-5555-5555-555555555555"
    monkeypatch.setenv("BOOTSTRAP_INSTANCE_ID", iid)
    monkeypatch.setenv("BOOTSTRAP_INSTANCE_TOKEN", "seed-tok")
    monkeypatch.setenv("BOOTSTRAP_CLIENT_ID", cid)
    monkeypatch.setenv("BOOTSTRAP_ACCOUNT_ID", aid)
    seed_demo_instance()
    sm = get_sessionmaker()
    with sm() as s:
        assert s.get(Client, uuid.UUID(cid)) is not None
        acc = s.get(ExchangeAccount, uuid.UUID(aid))
        assert acc is not None and acc.exchange == "bybit"
        inst = s.get(Instance, uuid.UUID(iid))
        assert inst is not None and str(inst.client_id) == cid and str(inst.account_id) == aid
