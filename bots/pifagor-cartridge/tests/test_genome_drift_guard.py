"""Страж-дрейфа живого генома (ADR-0019, условие подписи Куратора по F1).

Инвариант: замороженный архив b75bd17 неизменен; живой субсет `bots/pifagor/vendor/` = архив +
ТОЛЬКО санкционированные дельты (каждая = свой ADR). Тест сверяет git-ОТСЛЕЖИВАЕМОЕ дерево вендора с
манифестом `genome_manifest.json`: любая НЕсанкционированная правка/добавление/удаление файла генома
ИЛИ вторая дельта без ADR → красный CI. Рантайм-состояние (pifagor.db*) gitignored → вне генома.
Вторая дельта — только осознанно: новый ADR + регенерация манифеста + правка ожидания ниже."""
import hashlib
import json
import os
import subprocess

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))   # tests → cartridge → bots → repo
_VENDOR_REL = "bots/pifagor/vendor"
_MANIFEST = os.path.join(_HERE, "genome_manifest.json")


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _tracked_vendor_files():
    """{relpath-от-vendor: abspath} git-отслеживаемых файлов генома (== «что закоммичено»;
    gitignored рантайм pifagor.db* сюда не попадает)."""
    out = subprocess.run(
        ["git", "-C", _ROOT, "ls-files", _VENDOR_REL],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    return {os.path.relpath(t, _VENDOR_REL): os.path.join(_ROOT, t) for t in out}


def _manifest():
    with open(_MANIFEST, encoding="utf-8") as f:
        return json.load(f)


def test_genome_no_unsanctioned_drift():
    m = _manifest()
    frozen, sanctioned = m["frozen"], m["sanctioned"]
    current = _tracked_vendor_files()
    manifest_paths = set(frozen) | set(sanctioned)

    # (1) состав не изменился — ни добавленных, ни пропавших файлов генома
    assert set(current) == manifest_paths, (
        f"дрейф состава vendor: добавлены {sorted(set(current) - manifest_paths)}, "
        f"пропали {sorted(manifest_paths - set(current))}")

    # (2) заморожённые файлы — байт-в-байт b75bd17 (ни строки постороннего кода движка)
    drift = [p for p, sha in frozen.items() if _sha256(current[p]) != sha]
    assert not drift, (
        f"НЕсанкционированная правка vendor (Закон 6/ADR-0016): {drift}. "
        "Живой геном меняют санкц. дельтой = отдельный ADR + регенерация манифеста.")

    # (3) санкционированная дельта совпадает с пиннутым хешем (правка разъёма — только осознанно)
    for p, meta in sanctioned.items():
        assert _sha256(current[p]) == meta["sha256"], (
            f"{p}: дельта изменилась — перегенерируй манифест под {meta.get('adr')}")


def test_exactly_registered_sanctioned_deltas():
    """Реестр дельт (ADR-0019 + ADR-0021): ровно ДВЕ — монеты (config/strategy.py, 0019) +
    warm-ритм (app/main.py + app/cycle.py, 0021). Третья дельта обязана пройти свой ADR
    (правка этого ожидания = видимый триггер для ревью)."""
    m = _manifest()
    by_adr = {}
    for p, meta in m["sanctioned"].items():
        by_adr.setdefault(meta["adr"], []).append(p)
    assert {k: sorted(v) for k, v in by_adr.items()} == {
        "ADR-0019": ["config/strategy.py"],
        "ADR-0021": ["app/cycle.py", "app/main.py"],
    }, "новая санкционированная дельта живого генома — только отдельным ADR (закон эталона)"
