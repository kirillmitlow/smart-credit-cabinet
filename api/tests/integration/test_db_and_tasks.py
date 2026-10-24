"""T-201/T-205/T-204: миграции под блокировкой, модели = схема, задачи после коммита, сброс демо."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from typing import Any

import pytest
import redis
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text

import app.shared.models  # noqa: F401
from app.shared import db, resets, tasks
from app.shared.db import Base, alembic_config, migrate, schema_is_current
from app.shared.errors import AppError

pytestmark = pytest.mark.integration


@pytest.fixture
def database(postgres_url: str) -> Iterator[db.Database]:
    database = db.configure(postgres_url)
    migrate(database.engine)
    yield database
    database.dispose()


def test_parallel_starts_wait_for_lock_and_see_ready_schema(postgres_url: str) -> None:
    engines = [create_engine(postgres_url) for _ in range(3)]
    errors: list[BaseException] = []

    def start(engine: Any) -> None:
        try:
            migrate(engine)
        except BaseException as exc:  # noqa: BLE001 — собираем для проверки
            errors.append(exc)

    threads = [threading.Thread(target=start, args=(e,)) for e in engines]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert all(schema_is_current(e) for e in engines)
    for e in engines:
        e.dispose()


def test_models_match_schema_after_migrations(database: db.Database) -> None:
    with database.engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_downgrade_and_upgrade_round_trip(postgres_url: str, database: db.Database) -> None:
    cfg = alembic_config(postgres_url)
    command.downgrade(cfg, "base")
    assert not schema_is_current(database.engine)
    command.upgrade(cfg, "head")
    assert schema_is_current(database.engine)


def test_status_is_string_with_check(database: db.Database) -> None:
    def insert_bad() -> None:
        with database.transaction() as s:
            s.execute(
                text(
                    "INSERT INTO outbox (aggregate_id, event_type, target_system, payload,"
                    " idempotency_key, status, attempts, next_attempt_at, created_at)"
                    " VALUES ('a', 'E', 'BKI', '{}', 'k-check', 'LOST', 0, now(), now())"
                )
            )

    with pytest.raises(Exception, match="ck_outbox_status"):
        insert_bad()


def test_task_is_sent_only_after_commit(
    database: db.Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(tasks, "send_now", lambda name, **kw: sent.append((name, kw)))

    def enqueue_then_fail() -> None:
        with database.transaction() as session:
            tasks.enqueue(session, "pipeline.run", application_id="rolled-back")
            raise RuntimeError("откат")

    with pytest.raises(RuntimeError):
        enqueue_then_fail()
    assert sent == []

    with database.transaction() as session:
        tasks.enqueue(session, "pipeline.run", application_id="a1")
        assert sent == []  # до коммита задачи нет
    assert sent == [("pipeline.run", {"application_id": "a1"})]


def test_task_by_name_lands_in_its_queue_without_importing_worker(redis_url: str) -> None:
    tasks.configure_celery(redis_url.replace("/0", "/1"))
    tasks.send_now("pipeline.run", application_id="a1")
    broker = redis.Redis.from_url(redis_url.replace("/0", "/1"))
    assert broker.llen("pipeline") == 1


def test_request_id_travels_in_task_headers() -> None:
    import structlog

    structlog.contextvars.bind_contextvars(requestId="req_task")
    headers: dict[str, Any] = {}
    tasks._attach_request_id(headers=headers)
    assert headers["requestId"] == "req_task"

    class FakeTask:
        name = "pipeline.run"

        class request:  # noqa: N801 — так устроен объект задачи Celery
            requestId = "req_task"  # noqa: N815

    structlog.contextvars.clear_contextvars()
    tasks._bind_request_id(task=FakeTask())
    assert structlog.contextvars.get_contextvars()["requestId"] == "req_task"
    tasks._unbind_request_id()


def test_resets_refuse_outside_demo_mode(
    database: db.Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(resets, "_registry", [("a", lambda s: calls.append("a"))])
    monkeypatch.setenv("DEMO_MODE", "false")
    from app.shared.settings import get_settings

    get_settings.cache_clear()

    def reset() -> list[str]:
        with database.transaction() as s:
            return resets.run_all_resets(s)

    with pytest.raises(AppError) as err:
        reset()
    assert err.value.code == "DEMO_DISABLED"
    monkeypatch.setenv("DEMO_MODE", "true")
    get_settings.cache_clear()
    with database.transaction() as s:
        assert resets.run_all_resets(s) == ["a"]
    assert calls == ["a"]


def test_callbacks_wait_for_outer_commit_and_task_can_observe_committed_data(
    database: db.Database,
) -> None:
    from uuid import uuid4

    key = f"commit-proof-{uuid4()}"
    seen: list[int] = []

    def observe() -> None:
        with database.engine.connect() as connection:
            seen.append(
                connection.scalar(
                    text("SELECT count(*) FROM outbox WHERE idempotency_key=:key"), {"key": key}
                )
            )

    with database.transaction() as session:
        with session.begin_nested():
            session.execute(
                text(
                    "INSERT INTO outbox (aggregate_id, event_type, target_system, payload, "
                    "idempotency_key, status, attempts, next_attempt_at, created_at) "
                    "VALUES ('after-commit', 'TEST_COMMIT', 'BKI', '{}', :key, 'PENDING', 0, now(), now())"
                ),
                {"key": key},
            )
            db.after_commit(session, observe)
        assert seen == []  # releasing the savepoint is not publishing the committed row
    assert seen == [1]
    with database.engine.begin() as connection:
        connection.execute(text("DELETE FROM outbox WHERE idempotency_key=:key"), {"key": key})


def test_released_savepoint_then_outer_rollback_publishes_nothing(
    database: db.Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[str] = []
    monkeypatch.setattr(tasks, "send_now", lambda name, **kw: sent.append(name))

    def run_then_rollback() -> None:
        with database.transaction() as session:
            with session.begin_nested():
                tasks.enqueue(session, "pipeline.run", application_id="not-committed")
            assert sent == []
            raise RuntimeError("outer rollback")

    with pytest.raises(RuntimeError, match="outer rollback"):
        run_then_rollback()
    assert sent == []


def test_nested_rollback_discards_only_its_subtree(database: db.Database) -> None:
    called: list[str] = []
    with database.transaction() as session:
        db.after_commit(session, lambda: called.append("outer-before"))

        def roll_parent_back() -> None:
            with session.begin_nested():
                db.after_commit(session, lambda: called.append("rolled-parent"))
                with session.begin_nested():
                    db.after_commit(session, lambda: called.append("released-child"))
                assert called == []
                raise RuntimeError("parent rollback")

        with pytest.raises(RuntimeError, match="parent rollback"):
            roll_parent_back()
        with session.begin_nested():
            db.after_commit(session, lambda: called.append("kept-child"))
        db.after_commit(session, lambda: called.append("outer-after"))
        assert called == []
    assert called == ["outer-before", "kept-child", "outer-after"]


@pytest.mark.parametrize("finish", ["rollback", "close", "commit"])
def test_session_reuse_never_republishes_old_callbacks(database: db.Database, finish: str) -> None:
    called: list[str] = []
    with database.sessions() as session:
        session.begin()
        db.after_commit(session, lambda: called.append("old"))
        getattr(session, finish)()
        assert called == (["old"] if finish == "commit" else [])
        with session.begin():
            db.after_commit(session, lambda: called.append("new"))
    assert called == (["old", "new"] if finish == "commit" else ["new"])


def test_failed_callback_is_not_replayed_by_next_transaction(database: db.Database) -> None:
    called: list[str] = []

    def fail() -> None:
        called.append("failed")
        raise RuntimeError("delivery unavailable")

    with database.sessions() as session:
        with pytest.raises(RuntimeError, match="delivery unavailable"):
            with session.begin():
                db.after_commit(session, fail)
        session.close()  # committed DB transaction cannot be rolled back after delivery failed
        with session.begin():
            db.after_commit(session, lambda: called.append("next"))
    assert called == ["failed", "next"]


def test_callback_registration_requires_active_transaction(database: db.Database) -> None:
    with database.sessions() as session:
        with pytest.raises(ValueError, match="active transaction"):
            db.after_commit(session, lambda: None)
