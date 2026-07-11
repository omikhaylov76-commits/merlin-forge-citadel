"""Conformance-тест шва S5: контракт InfraDriver, который обязан пройти любой драйвер.

FakeDriver гоняем через полный контракт (deploy→status→destroy идемпотентно). DockerDriver-заглушку
гвоздим на явный NotImplementedError (шумная заглушка, seams). Плюс round-trip формата infra_ref.
"""

import pytest

from app.infra.base import DeploySpec, InfraStatus, make_ref, parse_ref
from app.infra.docker import DockerDriver
from app.infra.fake import FakeDriver


def _spec(name="mfc-inst-abc") -> DeploySpec:
    return DeploySpec(image="paper-bot:v0", name=name, env={"MFC_INSTANCE_ID": "abc"})


# ── формат infra_ref (SCL8) ─────────────────────────────────────────────────

def test_ref_roundtrip():
    ref = make_ref("proj-1", "mfc-inst-abc")
    assert ref == "railway:proj-1:mfc-inst-abc"
    assert parse_ref(ref) == ("railway", "proj-1", "mfc-inst-abc")


def test_parse_ref_rejects_malformed():
    for bad in ("railway:only-two", "a:b:c:d", "::", "railway::svc"):
        with pytest.raises(ValueError):
            parse_ref(bad)


# ── контракт драйвера на FakeDriver ─────────────────────────────────────────

def test_deploy_then_status_running():
    d = FakeDriver()
    ref = d.deploy(_spec())
    assert parse_ref(ref)[0] == "railway"
    assert d.status(ref) == InfraStatus.RUNNING


def test_deploy_idempotent_by_name():
    d = FakeDriver()
    r1 = d.deploy(_spec("mfc-inst-x"))
    r2 = d.deploy(_spec("mfc-inst-x"))  # тот же name → усыновление, тот же ref (не дубль)
    assert r1 == r2
    assert len(d._services) == 1


def test_destroy_is_idempotent():
    d = FakeDriver()
    ref = d.deploy(_spec())
    d.destroy(ref)
    assert d.status(ref) == InfraStatus.ABSENT
    d.destroy(ref)  # повторный destroy отсутствующего = успех (OPS5), не исключение


# ── заглушка DockerDriver шумит (не молчит) ─────────────────────────────────

def test_docker_driver_is_loud_stub():
    d = DockerDriver()
    with pytest.raises(NotImplementedError):
        d.deploy(_spec())
    with pytest.raises(NotImplementedError):
        d.destroy("railway:p:s")
    with pytest.raises(NotImplementedError):
        d.status("railway:p:s")
