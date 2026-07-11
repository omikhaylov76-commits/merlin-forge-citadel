# -*- coding: utf-8 -*-
"""state.config — ConfigStore: рантайм-крутилки поверх storage.db (Веха 4 фича 2, docs/14 §3).

Тонкий слой над db.config_* + реестром config.knobs: валидируемый set (= «применить»), типизированное
чтение ЭФФЕКТИВНОГО значения (override из config_state, иначе дефолт env/config), журнал. config_state
хранит TEXT — типизация/валидация через config.knobs (единый источник). Кросс-кноб инварианты
(0<ALARM_DD<KILLSWITCH_DD<1) проверяются против эффективного конфига. Pending→«Применить» и UI —
фичи 3/4; чтение движком на старте 4h-цикла — Веха 5.
"""
from config import knobs
from logging_.trade_logger import get_logger

_log = get_logger("pifagor.config")


class ConfigError(Exception):
    """Эффективный конфиг нарушает кросс-кноб инвариант (вне-полосная порча ОБОИХ DD в обход set)."""


class ConfigStore:
    """Рантайм-крутилки поверх storage.db.DB."""

    def __init__(self, db):
        self.db = db

    def raw(self, key):
        """Только override из config_state (типизированный) или None, если не задан. ОТКАЗОУСТОЙЧИВО:
        невалидный override (непарсимый ТИП, вне диапазона/enum, устаревший после ужесточения KNOB_SPECS,
        ручная порча БД) трактуем как «нет override» -> get падает назад на дефолт (read-path движка на
        старте 4h-цикла не должен ни ронять, ни сервить вне-диапазонное значение; наблюдаемость — лог
        вызывающего, Веха 5). Полный гейт = knobs.validate (тип+диапазон+enum), не только коерсия."""
        txt = self.db.config_get(key)
        if txt is None:
            return None
        ok, _ = knobs.validate(key, txt)
        return knobs.coerce(key, txt) if ok else None

    def get(self, key):
        """ЭФФЕКТИВНОЕ значение: override из config_state, иначе дефолт env/config (read-path движка/UI)."""
        ov = self.raw(key)
        return ov if ov is not None else knobs.default(key)

    def all(self):
        """{key: эффективное значение} по всем известным крутилкам."""
        return {k: self.get(k) for k in knobs.KNOBS}

    def effective(self, *, strict=False):
        """Снимок ЭФФЕКТИВНОГО конфига {key: значение} (= all()) — read-path движка (Веха 5: старт 4h-цикла).
        strict=True -> пере-ассертит кросс-кноб инвариант (0<ALARM_DD<KILLSWITCH_DD<1) на эффективном наборе
        и бросает ConfigError при нарушении (ловит вне-полосную порчу ОБОИХ DD в обход set; per-knob read-path
        fail-safe этого не чинит — какой из двух «неверный», неоднозначно). RISK_PCT_ALARM > RISK_PCT_PER_LEG —
        НЕ ошибка (тревога ПОВЫШАЕТ риск = выбор владельца, docs/04): warning, не исключение."""
        eff = self.all()
        ra, rp = eff.get("RISK_PCT_ALARM"), eff.get("RISK_PCT_PER_LEG")
        if ra is not None and rp is not None and ra > rp:
            _log.warning("config: RISK_PCT_ALARM (%s) > RISK_PCT_PER_LEG (%s) — тревога ПОВЫШАЕТ риск "
                         "(выбор владельца, docs/04)", ra, rp)
        if strict:
            ok, err = knobs.cross_check(eff)
            if not ok:
                raise ConfigError(err)
        return eff

    def overrides(self):
        """Только реально заданные ВАЛИДНЫЕ override (типизированные); неизвестные/непарсимые/вне-диапазона
        отброшены (fail-safe через knobs.validate, как raw)."""
        out = {}
        for k, v in self.db.config_all().items():
            if k not in knobs.KNOB_SPECS:
                continue
            ok, _ = knobs.validate(k, v)
            if ok:
                out[k] = knobs.coerce(k, v)
        return out

    def set(self, key, value, *, source="dashboard", applied_from_bar=None):
        """Валидирует (тип/диапазон/enum + кросс-кноб против эффективного) и применяет в config_state +
        журнал. Возвращает (ok, err). При невалидном — НИЧЕГО не пишет. no-op (значение не изменилось)
        тоже (True, None), но без записи в журнал (db.config_apply сам отсекает old==new)."""
        ok, err = knobs.validate(key, value)
        if not ok:
            return False, err
        val = knobs.coerce(key, value)
        ok, err = self._cross_check(key, val)
        if not ok:
            return False, err
        self.db.config_apply(key, val, source=source, applied_from_bar=applied_from_bar)
        return True, None

    def _cross_check(self, key, val):
        """Инвариант 0<ALARM_DD<KILLSWITCH_DD<1 (порядок; доли в (0,1) уже проверены validate). ЕДИНЫЙ
        источник — knobs.cross_check (DRY с config.validate / effective). ФОРСИТСЯ ТОЛЬКО НА ЗАПИСИ (set):
        строим эффективную пару с предлагаемым значением. Read-path (raw/get) кросс-кноб НЕ авто-чинит (какой
        из двух «неверный» — неоднозначно); effective(strict=True) пере-ассертит на старте 4h-цикла (Веха 5)."""
        if key not in ("ALARM_DD", "KILLSWITCH_DD"):
            return True, None
        pair = {"ALARM_DD": self.get("ALARM_DD"), "KILLSWITCH_DD": self.get("KILLSWITCH_DD"), key: val}
        return knobs.cross_check(pair)

    def log(self, param=None, limit=None):
        """Журнал изменений (новые сверху). param — фильтр, limit — N последних."""
        return self.db.config_log_all(param=param, limit=limit)

    def record_action(self, action, detail=None, *, source="action"):
        """Записать ДЕЙСТВИЕ оператора (напр. «Закрыть всё») в журнал config_log БЕЗ записи в config_state.
        Audit-строка (param=action, old=None, new=detail); get()/all()/overrides() её НЕ видят (читают только
        config_state). Возвращает id строки журнала. Enforcement действия — Веха 5 (читает журнал/флаг)."""
        return self.db.config_log_append(action, None, detail, source=source)
