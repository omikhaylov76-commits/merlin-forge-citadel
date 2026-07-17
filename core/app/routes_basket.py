"""Роутер Набора Оператора (НАБОР-1, витрина+хранение).

Оператор отмечает сетап звёздочкой → монета с контекстом сетапа складывается в ГЛОБАЛЬНУЮ корзину;
отдельный вид — посмотреть/убрать лишнее. НИЧЕГО не торгует (НАБОР-2 — «запустить в работу», боевой
мост — строго отдельной спекой Куратора, не здесь). Каждое add/remove — строка audit_log (закон №4).
Только операторский токен (require_role operator); портал прав на Набор не имеет (закон №5).
context — недоверенный JSON снимка сетапа, экранируется на ВЫВОДЕ (фронт), как scout/screener (#53).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.auth import require_role
from app.db import get_session
from app.models import BasketItem, User

router = APIRouter(prefix="/v1/basket")


class BasketAdd(BaseModel):
    """Заявка на добавление сетапа в Набор (звёздочка). context — снимок сетапа (недоверен)."""

    symbol: str = Field(min_length=1, max_length=40)
    tf: str = Field(min_length=1, max_length=4)
    source: str = Field(pattern="^(scout|screener)$")
    context: dict = Field(default_factory=dict)
    note: str | None = Field(default=None, max_length=500)


def _item_dict(it: BasketItem) -> dict:
    return {
        "id": str(it.id),
        "symbol": it.symbol,
        "tf": it.tf,
        "source": it.source,
        "context": it.context,  # недоверенный JSON — экранируется фронтом на выводе
        "note": it.note,
        "created_at": it.created_at.isoformat() if it.created_at else None,
    }


@router.get("/items")
def list_basket(
    operator: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
) -> list[dict]:
    """Содержимое Набора (свежие сверху). Чтение — без аудита."""
    rows = (
        session.execute(select(BasketItem).order_by(BasketItem.created_at.desc()))
        .scalars()
        .all()
    )
    return [_item_dict(r) for r in rows]


@router.post("/items", status_code=status.HTTP_201_CREATED)
def add_basket(
    body: BasketAdd,
    operator: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
) -> dict:
    """Отметить сетап → в Набор. Upsert по (symbol, tf): повторная звёздочка обновляет контекст/
    источник, не плодит дубли. Действие оператора → audit_log (№4)."""
    stmt = (
        pg_insert(BasketItem)
        .values(
            symbol=body.symbol,
            tf=body.tf,
            source=body.source,
            context=body.context,
            note=body.note,
            added_by=operator.id,
        )
        .on_conflict_do_update(
            constraint="uq_basket_symbol_tf",
            set_={
                "source": body.source,
                "context": body.context,
                "note": body.note,
                "added_by": operator.id,
            },
        )
        .returning(BasketItem.id)
    )
    item_id = session.execute(stmt).scalar_one()
    write_audit(
        session,
        actor=str(operator.id),
        action="basket_item_added",
        entity=str(item_id),
        after={"symbol": body.symbol, "tf": body.tf, "source": body.source},
    )
    session.commit()
    return _item_dict(session.get(BasketItem, item_id))


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_basket(
    item_id: uuid.UUID,
    operator: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
) -> None:
    """Убрать элемент из Набора. Действие оператора → audit_log (№4)."""
    it = session.get(BasketItem, item_id)
    if not it:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "нет такого элемента Набора")
    before = {"symbol": it.symbol, "tf": it.tf, "source": it.source}
    session.delete(it)
    write_audit(
        session,
        actor=str(operator.id),
        action="basket_item_removed",
        entity=str(item_id),
        before=before,
    )
    session.commit()
