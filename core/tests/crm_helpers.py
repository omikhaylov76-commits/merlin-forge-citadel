"""Хелпер тестов Ф3: у instances включены FK client_id/account_id (миграция 0005) — инстансу
теперь нужны РОДИТЕЛИ. Тесты, что создают Instance напрямую, зовут ensure_parents перед вставкой."""

from app.models import Client, ExchangeAccount


def ensure_parents(session, client_id, account_id):
    """Идемпотентно создать client + exchange_account под инстанс (FK Ф3).
    Возвращает (client_id, account_id). Родитель по id уже есть → пропуск (несколько инстансов
    на один account_id — валидно для теста уникального индекса)."""
    if session.get(Client, client_id) is None:
        session.add(Client(id=client_id, name="test client"))
    if session.get(ExchangeAccount, account_id) is None:
        session.add(ExchangeAccount(id=account_id, client_id=client_id, exchange="bybit"))
    session.flush()  # родители материализованы до вставки инстанса
    return client_id, account_id
