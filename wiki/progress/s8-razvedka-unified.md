---
type: progress
title: S8→Ф5 Единая Разведка — «чьими глазами» + правда движка per-coin (подпись Куратора 2026-07-22)
tags: [progress, s8, f5, razvedka-unified, engine-truth, scout, contract, console]
updated: 2026-07-22
---

# Единая Разведка — план постройки

Подписано Куратором (QUEUE 2026-07-22, «Строй»): 3 пункта закрыты — (1) поле «правда движка»
per-coin в telemetry-scout ПОДПИСАНО; (2) SIGNAL_TF = readout-гвоздь «4h» (knob — Кузница/Ф5),
«представитель» УБРАН; (3) F-warm-button уже жив (ADR-0022) — переиспользуем.
Дизайн: `_curator/design/razvedka-unified-design.md` + mockup (одобрены целиком).

## Разведка (что уже есть — сверено кодом)

- **Движок:** `vendor/strategy/warm.py::classify` → дескриптор {kind PENDING|OPEN, auto_eligible,
  reanchored, side, A/B, entries{0.382/0.5/0.618}, stop, targets, age_bars, est_risk_pct, note}
  или None (нет активного пробоя / отработан / вне COINS_CONFIG). ТА ЖЕ функция, что решает
  постановку (самоход `_warm_one` / кнопка `_warm_one_button`).
- **Адаптер:** `scout_reader.py::_verified_grid` УЖЕ зовёт classify (held-монеты, F-scout-snap);
  `build_snapshots(held)` собирает контрактные снимки. `bot.py::_push_scout` пушит по курсору
  скана/смене held.
- **Контракт:** `contracts/telemetry-scout.schema.json` — аддитивные поля-прецеденты
  (`verified`/`klines_tf`/`bars_since_anchor`). Ядро: `routes_telemetry.py` полное Pydantic-зеркало
  + REPLACE-хранение `scout_snapshots`; readout `/v1/instances/{id}/scout`.
- **Консоль:** `Scout.tsx` — доска по СТАДИИ скаута (forming/tracking/ready/committed) +
  «представитель» (freshest) + ТФ-тумблер 4h/1h. Всё это уходит по дизайну.
- **Стек движка:** провайдер динамики (`bot.py` `self._provider`) знает рабочую вселенную —
  для факта `in_universe` (F-lookahead «мимо списка»).

## Слои постройки

### Слой 1 — адаптер: правда движка per-coin (0-vendor)
`scout_reader.py`:
- [x] `_engine_truth(symbol)` — classify на 4h-свечах scout.db (расширение `_verified_grid`,
      fail-soft per-coin: упал реплей → снимок БЕЗ engine-поля, не роняем пуш).
- [x] `build_snapshots(held, universe=None)`: для КАЖДОЙ 4h-находки (+held-синтез) — поле
      `engine` = {checked, kind|null, auto_eligible, reanchored, in_universe, side?, age_bars?,
      entries?, stop?, targets?, est_risk_pct?}. `in_universe` = symbol ∈ universe (стек динамики;
      None → COINS_CONFIG.enabled вендора — фикс-боты).
- [x] `bot.py`: прокинуть `universe=` из провайдера (есть только у динамик-ботов).
- [x] `mapper.py::scout_snapshot(..., engine=None)` — аддитивно, None → ключа нет (флот чист).
- [x] Замер: лог длительности прохода classify по находкам (десятки монет × numpy-реплей — дёшево;
      подтвердить логом на живом).

### Слой 2 — Контракт + ядро (schema-first)
- [x] `telemetry-scout.schema.json`: опц. объект `engine` (additionalProperties:false; enum kind;
      числовые сетки >0 где уместно) + описание «факты warm.classify, снимок скаута — не живой тик».
- [x] `routes_telemetry.py`: Pydantic-зеркало `ScoutEngine` (опц. поле снимка) — сквозь REPLACE
      в JSON и readout без потерь.
- [x] Sync-гвозди: тест схема↔зеркало (обе стороны, паттерн #52) + тест readout отдаёт engine.

### Слой 3 — консоль: доска-по-вердикту
- [x] `api.ts`: тип `ScoutEngine`; УБРАТЬ «представителя» (freshest-дефолт) — селектор
      «чьими глазами» per-инстанс (+роль бота: LIVE·demo/динамик/скаут); дефолт = первый видимый /
      последний выбранный (localStorage).
- [x] `Scout.tsx` — 4 колонки ПО ВЕРДИКТУ (из фактов engine, лексика в консоли):
      🟢 в работе (has_active: position/orders) · 🟡 готов·ставит (PENDING·auto_eligible·in_universe)
      · 🟠 нужна кнопка (PENDING·reanchored·in_universe; кнопка «Поставить» = warm_apply ADR-0022)
      · ⚫ не берёт + причина/судьба (None+forming→«созревает»; None+уровни были→«отработан»;
      годный∉universe→«мимо списка» F-lookahead; OPEN→«вход по рынку ушёл»).
- [x] Карточка: строка радара (стадия+скор) · спарклайн + медная зона входа 0.382–0.618 ·
      %-до-входа/возраст · строка вердикта · сетка (входы/стоп) · ★ Набор · клик → ScoutDetail.
      **Дисклеймер «снимок скаута, не живой тик» — ОБЯЗАТЕЛЕН (условие подписи ADR-0021-тонкость).**
- [x] ТФ: тумблер УБРАТЬ → readout «торговый ТФ 4h · наследуется от бота» (гвоздь до Ф5;
      1h-снимки — свёрнутый хвост «не-торговый ТФ: N», не доска).
- [x] Вариант А: DozorPanel — кнопка «Подтвердить для <имя бота>» (текст с именем); после PUT —
      подсказка «скаут пересобирает ~6 мин». Горн (scan_now) и «Подтвердить» — раздельно, как есть.
- [x] Сайдбар: в группе Кузница — Конструктор ПЕРВЫМ (· Разведка · Скринер · Профили).
- [x] Пустые состояния/ошибки — сохранить 3+1 (#53), тексты под вердикт-доску.

### Слой 4 — доказательства
- [x] Тесты vs НАСТОЯЩИЙ вендор (урок S7, subprocess-паттерн): engine-поле на живом classify —
      auto_eligible PENDING → auto; reanchored → button; закрытый реплей → None; вне universe →
      in_universe=false. Ядро: зеркало+readout. tsc чист.
- [x] Code-review (адверсариальный) → merge (--no-ff) → деплой Борс+ядро+консоль.
- [ ] ЖИВАЯ сверка на Борсе: Оператор смотрит его глазами — радар vs движок; колонки сходятся с
      логами (`горн: проверено N`, warm_apply skip-строки). — ГЕЙТ живого показа (Оператор)
- [x] Вики: telemetry-schemas + bot-contract страницы, index, log (handoff — на закрытии сессии).

## Границы
0-vendor (classify только ВЫЗЫВАЕТСЯ; правка генома → СТОП+доклад). Портал не видит (Закон 5 —
readout операторский). Персиваль/Галахад НЕ передеплоим (образ общий, поле дормантно до их
деплоя — поведение не меняется, пуш тот же). Демо. Тейк-профит 1-й ноги — НЕ здесь.

## SHA
- ветка `feat/razvedka-unified` от `78cde14`: слои 1–2 `4cff690` · слой 3 консоль `100e1a2` ·
  фиксы само-ревью (накопительный warm-список; сетка движка в детали) `0226db5`.
- merge в main **`c4e199a`** (--no-ff), ветка удалена. Локально: картридж 204 + core 32, ruff/tsc
  чисты, build чист (npm ci починил локальную сборку). **CI на main SUCCESS.**
- Деплой: ядро `serviceInstanceDeploy` (:main, healthz 200 + маршрут 401) · Борс `cd8d0534`
  serviceInstanceDeploy (LIVE=1/DYNAMIC=1/SCOUT=1/самоход WARM_EACH_CYCLE=1 сохранены; стражи
  Персиваль/Галахад штампы неизменны) · консоль `railway up` SUCCESS (деплой 4028399b).
- **Живой boot Борса ЧИСТ:** `движок [LIVE demo] рестартов=0`, `reconcile_on_start: {}`, новая строка
  `scout: снимков 2, правда движка за 0.00с` (замер дёшев), 0×422, 0 трейсбеков. Осталось: визуальная
  сверка Оператором (глазами Борса на консоли — гейт живого показа).
