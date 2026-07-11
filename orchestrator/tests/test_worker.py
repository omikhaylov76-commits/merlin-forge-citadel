"""Worker: диспетч по kind + отображение исходов на ack (done/release/failed). Драйвер — FakeDriver,
ядро — in-memory FakeCore (проверяем, ЧЕМ воркер ack'ает, не гоняя HTTP)."""

from app.core_client import Lease
from app.infra.base import DeploySpec, InfraStatus
from app.infra.fake import FakeDriver
from app.worker import process_once


class FakeCore:
    """Заглушка CoreClient: отдаёт заранее сложенные аренды, записывает ack'и."""

    def __init__(self, leases=()):
        self._leases = list(leases)
        self.acks: list[dict] = []

    def lease_next(self, *, wait):
        return self._leases.pop(0) if self._leases else None

    def ack(self, *, job_id, lease_nonce, result, detail=None, terminal=False):
        self.acks.append(
            {"job_id": job_id, "nonce": lease_nonce, "result": result,
             "detail": detail, "terminal": terminal}
        )


def _lease(kind="deploy", payload=None, jid="job-1") -> Lease:
    default = {"image": "paper:v0", "name": "mfc-inst-abc", "env": {}} if kind == "deploy" else {}
    return Lease(id=jid, kind=kind, instance_id="inst-1",
                 payload=payload if payload is not None else default, lease_nonce="nonce-1")


def test_empty_lease_returns_false():
    core, driver = FakeCore(), FakeDriver()
    assert process_once(core, driver, wait=0) is False
    assert core.acks == []  # ничего не арендовали → ничего не ack'аем


def test_deploy_happy_acks_done_with_infra_ref():
    core, driver = FakeCore([_lease("deploy")]), FakeDriver()
    assert process_once(core, driver, wait=0) is True
    (ack,) = core.acks
    assert ack["result"] == "done"
    assert ack["detail"]["infra_ref"] == "railway:fake:mfc-inst-abc"
    assert ack["nonce"] == "nonce-1"                       # fencing-nonce возвращён (OPS2)
    assert driver.status(ack["detail"]["infra_ref"]) == InfraStatus.RUNNING  # сервис реально поднят


def test_teardown_happy_destroys_and_acks_done():
    driver = FakeDriver()
    ref = driver.deploy(DeploySpec(image="p", name="mfc-inst-abc"))  # поднять — будет что сносить
    core = FakeCore([_lease("teardown", payload={"infra_ref": ref})])
    assert process_once(core, driver, wait=0) is True
    assert core.acks[0]["result"] == "done"
    assert driver.status(ref) == InfraStatus.ABSENT  # снесён


def test_infra_error_acks_release():
    driver = FakeDriver()
    driver.fail_next = 1  # инъекция отказа инфры на ближайший вызов
    core = FakeCore([_lease("deploy")])
    process_once(core, driver, wait=0)
    assert core.acks[0]["result"] == "release"  # отпуск без штрафа (OPS16)


def test_unknown_kind_acks_failed_terminal():
    core = FakeCore([_lease("backtest")])
    process_once(core, FakeDriver(), wait=0)
    assert core.acks[0]["result"] == "failed"
    assert core.acks[0]["terminal"] is True


def test_bad_deploy_payload_acks_failed_terminal():
    core = FakeCore([_lease("deploy", payload={"name": "mfc-inst-abc"})])  # нет image
    process_once(core, FakeDriver(), wait=0)
    assert core.acks[0]["result"] == "failed"
    assert core.acks[0]["terminal"] is True  # неустранимо → без ретраев
