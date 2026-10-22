"""T-372: замки компании, общий сброс, запоздавшее поколение и журналы."""

# ruff: noqa: PT012 — проверяем освобождение замков и откат целой транзакции при ошибке

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import Any

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError

from app.modules import applications, companies
from app.modules.applications.models import ApplicationEvent
from app.modules.companies.models import Company
from app.modules.demo.reset_all import exclusive
from app.shared import db, operations
from app.shared.errors import AppError
from tests.integration.support import Firm, Member, make_stand

pytestmark = pytest.mark.integration


@pytest.fixture
def stand(
    postgres_url: str, redis_url: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[dict[str, Any]]:
    firms = [
        Firm("one", "0017654322", "Одна", members=[Member("boss", "Один", "DIRECTOR", None)]),
        Firm("two", "0010000000", "Другая", members=[Member("boss", "Два", "DIRECTOR", None)]),
    ]
    with make_stand(postgres_url, redis_url, monkeypatch, firms) as result:
        try:
            yield result
        finally:
            with db.transaction() as session:
                session.execute(text("TRUNCATE applications, companies, users, outbox CASCADE"))


def provider(stand: dict[str, Any], who: str = "one") -> Any:
    return lambda: companies.operation_scope(stand["companies"][who])


def test_company_reset_excludes_its_operations_but_not_neighbour(stand: dict[str, Any]) -> None:
    with operations.hold(provider(stand), exclusive=True) as scope:
        assert scope is not None
        assert scope.generation == 0
        with pytest.raises(operations.ResetInProgress):
            with operations.hold(provider(stand)):
                pytest.fail("Операция компании не должна пройти")
        with operations.hold(provider(stand, "two"), exclusive=True) as neighbour:
            assert neighbour.company_id == stand["companies"]["two"]
        with pytest.raises(AppError, match="Сброс уже выполняется"):
            with exclusive():
                pytest.fail("Общий сброс не должен пересечь сброс компании")


def test_active_operation_blocks_reset_and_releases_on_error(stand: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="operation failed"):
        with operations.hold(provider(stand)):
            with pytest.raises(operations.ResetInProgress):
                with operations.hold(provider(stand), exclusive=True):
                    pytest.fail("Сброс не должен пересечь активную операцию")
            raise ValueError("operation failed")
    with operations.hold(provider(stand), exclusive=True) as scope:
        assert scope is not None  # соединение не вернулось в пул с забытым session lock


def test_global_reset_excludes_operations(stand: dict[str, Any]) -> None:
    with exclusive():
        with pytest.raises(operations.ResetInProgress):
            with operations.hold(provider(stand)):
                pytest.fail("Операция не должна начаться во время общего сброса")


def test_partial_reset_flag_survives_and_only_allows_reset_retry(stand: dict[str, Any]) -> None:
    company_id = stand["companies"]["one"]
    with db.transaction() as session:
        company = session.get(Company, company_id)
        company.demo_generation += 1
        company.demo_resetting = True
    with pytest.raises(operations.ResetInProgress):
        with operations.hold(provider(stand)):
            pytest.fail("Незавершённый сброс должен закрывать обычные операции")
    with operations.hold(provider(stand), exclusive=True) as scope:
        assert scope.generation == 1
        assert scope.resetting is True


def test_delayed_old_generation_does_not_enter_operation(stand: dict[str, Any]) -> None:
    read, release = Event(), Event()
    first = True

    def delayed() -> operations.Scope | None:
        nonlocal first
        scope = provider(stand)()
        if first:
            first = False
            read.set()
            assert release.wait(5)
        return scope

    def old_job() -> None:
        with pytest.raises(operations.ResetInProgress):
            with operations.hold(delayed):
                pytest.fail("Запоздавшее старое поколение не должно писать")

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(old_job)
        try:
            assert read.wait(5)
            with operations.hold(provider(stand), exclusive=True):
                with db.transaction() as session:
                    row = session.get(Company, stand["companies"]["one"])
                    row.demo_generation += 1
        finally:
            release.set()
        future.result(timeout=5)


def test_journal_delete_whitelist_is_scoped_and_update_stays_forbidden(
    stand: dict[str, Any],
) -> None:
    application_ids = []
    for who in ("one", "two"):
        with db.transaction() as session:
            application = applications.Application(
                company_id=stand["companies"][who],
                created_by=stand["principals"][f"{who}:boss"].user_id,
                number=f"RESET-{who}",
                status="DRAFT",
                version=1,
                draft={},
                flags=[],
            )
            session.add(application)
            session.flush()
            applications.record_event(
                session, application, "STEP", actor_type=applications.Actor.SYSTEM
            )
            application_ids.append(application.id)
    own, foreign = application_ids
    with pytest.raises(DBAPIError, match="неизменяем"):
        with db.transaction() as session:
            session.execute(delete(ApplicationEvent).where(ApplicationEvent.application_id == own))
    with db.transaction() as session:
        session.execute(
            text("SELECT set_config('scc.demo_reset_ids', :ids, true)"), {"ids": str(own)}
        )
        session.execute(delete(ApplicationEvent).where(ApplicationEvent.application_id == own))
    with pytest.raises(DBAPIError, match="неизменяем"):
        with db.transaction() as session:
            session.execute(
                text("SELECT set_config('scc.demo_reset_ids', :ids, true)"), {"ids": str(own)}
            )
            session.execute(
                delete(ApplicationEvent).where(ApplicationEvent.application_id == foreign)
            )
    with pytest.raises(DBAPIError, match="неизменяем"):
        with db.transaction() as session:
            session.execute(
                text("SELECT set_config('scc.demo_reset_ids', :ids, true)"), {"ids": str(foreign)}
            )
            session.execute(update(ApplicationEvent).values(reason_code="MODIFIED"))
    with db.transaction() as session:
        remaining = session.scalars(select(ApplicationEvent.application_id)).all()
        assert remaining == [foreign]
