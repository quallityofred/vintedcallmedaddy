from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base, FoundItem, Monitor, SeenItem, User
from app.scheduler.dry_run import DryRunItem, MonitorDryRunResult
from app.web.api_dependencies import require_api_user
from app.web.dependencies import get_db
from app.web.diagnostics_api_router import router


def create_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def source_result(item_ids: tuple[int, ...] = (9101, 9102)) -> MonitorDryRunResult:
    items = [
        DryRunItem(
            id=str(item_id),
            title=f"Nike shoe {item_id}",
            brand_title="Nike",
            price=10.0,
            currency="EUR",
            url=f"https://www.vinted.pl/items/{item_id}-nike-shoe",
            domain="vinted.pl",
            source="hydration",
        )
        for item_id in item_ids
    ]
    return MonitorDryRunResult(
        monitor_id=22,
        selected_source="hydration",
        reason="catalog_filter_detected",
        selected_domains=["vinted.pl"],
        dry_run_domains=["vinted.pl"],
        counts_by_domain={"vinted.pl": len(items)},
        samples_by_domain={"vinted.pl": items},
        errors_by_domain={},
        pipeline_counts_by_domain={
            "vinted.pl": {
                "raw_fetched": len(items),
                "converted": len(items),
                "after_filters": len(items),
            }
        },
    )


@pytest_asyncio.fixture
async def route_context(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'baseline.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        user = User(
            id=1,
            username="baseline-user",
            password_hash="hash",
            password_salt="salt",
            is_admin=True,
        )
        monitor = Monitor(
            id=22,
            user_id=1,
            name="Nike shoes",
            original_url="https://www.vinted.pl/catalog?brand_ids[]=53&catalog[]=1231",
            params_json='{"brand_ids[]":["53"],"catalog[]":["1231"]}',
            domains_json='["vinted.pl"]',
            interval_sec=120,
            last_check_at=datetime(2026, 6, 7, tzinfo=timezone.utc),
        )
        session.add_all([user, monitor])
        await session.commit()

        app = create_test_app()
        app.dependency_overrides[require_api_user] = lambda: user

        async def override_db():
            yield session

        app.dependency_overrides[get_db] = override_db
        yield app, session, monitor
    await engine.dispose()


async def post_baseline(
    app: FastAPI,
    query: str = "",
    result: MonitorDryRunResult | None = None,
):
    with patch("app.web.diagnostics_api_router.VintedClient") as client_class, patch(
        "app.scheduler.dry_run.perform_monitor_dry_run",
        return_value=result or source_result(),
    ):
        client_class.return_value.close = AsyncMock()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.post(
                f"/api/v1/diagnostics/monitors/22/baseline-seen-no-notify{query}"
            )


async def count_rows(session: AsyncSession, model) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


def test_diagnostics_router_import_ok():
    from app.web.diagnostics_api_router import router as imported_router

    assert imported_router is not None


def test_backend_import_ok():
    from app.main import app

    assert app is not None


def test_baseline_seen_route_registered():
    paths = [route.path for route in create_test_app().routes]

    assert paths.count("/api/v1/diagnostics/monitors/{monitor_id}/baseline-seen-no-notify") == 1


@pytest.mark.asyncio
async def test_baseline_seen_route_returns_baseline_shape(route_context):
    app, _, _ = route_context
    response = await post_baseline(app, "?domain=vinted.pl&dry_run=true")

    assert response.status_code == 200
    data = response.json()
    assert data["reason"] == "baseline_seen_no_notify"
    assert data["summary"]["created_seen_items_total"] == 0
    assert data["summary"]["would_create_seen_items_total"] == 2
    assert data["summary"]["would_create_found_items_total"] == 0
    assert data["summary"]["would_enqueue_notifications_total"] == 0
    assert data["summary"]["would_send_telegram_total"] == 0
    assert data["side_effects"]["writes_found_items"] is False
    assert data["side_effects"]["enqueues_notifications"] is False
    assert data["side_effects"]["sends_telegram"] is False


@pytest.mark.asyncio
async def test_baseline_seen_route_dry_run_true_writes_nothing(route_context):
    app, session, _ = route_context
    before = await count_rows(session, SeenItem)
    response = await post_baseline(app, "?domain=vinted.pl&dry_run=true")
    after = await count_rows(session, SeenItem)

    assert response.status_code == 200
    assert before == after == 0
    assert response.json()["side_effects"]["writes_seen_items"] is False


@pytest.mark.asyncio
async def test_baseline_seen_route_default_dry_run_true(route_context):
    app, session, _ = route_context
    response = await post_baseline(app, "?domain=vinted.pl")

    assert response.status_code == 200
    assert await count_rows(session, SeenItem) == 0
    assert response.json()["dry_run"] is True


@pytest.mark.asyncio
async def test_baseline_seen_route_dry_run_false_creates_seen_items(route_context):
    app, session, _ = route_context
    before = await count_rows(session, SeenItem)
    response = await post_baseline(app, "?domain=vinted.pl&dry_run=false")
    after = await count_rows(session, SeenItem)

    assert response.status_code == 200
    assert before == 0
    assert after == 2
    assert response.json()["summary"]["created_seen_items_total"] == 2
    assert response.json()["side_effects"]["writes_seen_items"] is True


@pytest.mark.asyncio
async def test_baseline_seen_idempotent_second_run(route_context):
    app, session, _ = route_context
    first = await post_baseline(app, "?domain=vinted.pl&dry_run=false")
    second = await post_baseline(app, "?domain=vinted.pl&dry_run=false")

    assert first.json()["summary"]["created_seen_items_total"] == 2
    assert second.json()["summary"]["created_seen_items_total"] == 0
    assert second.json()["summary"]["already_seen_total"] == 2
    assert second.json()["side_effects"]["writes_seen_items"] is False
    assert await count_rows(session, SeenItem) == 2


@pytest.mark.asyncio
async def test_baseline_seen_then_full_cycle_reports_already_seen(route_context):
    app, _, _ = route_context
    one_item_result = source_result((9101,))
    baseline = await post_baseline(
        app,
        "?domain=vinted.pl&dry_run=false",
        one_item_result,
    )

    with patch("app.web.diagnostics_api_router.VintedClient") as client_class, patch(
        "app.scheduler.dry_run.perform_monitor_dry_run",
        side_effect=lambda *args, **kwargs: one_item_result,
    ):
        client_class.return_value.close = AsyncMock()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            full_cycle = await client.post(
                "/api/v1/diagnostics/monitors/22/dry-run-full-cycle?domain=vinted.pl"
            )

    assert baseline.json()["summary"]["created_seen_items_total"] == 1
    data = full_cycle.json()
    created_seen = baseline.json()["summary"]["created_seen_items_total"]
    assert data["summary"]["already_seen_total"] >= created_seen
    assert data["summary"]["would_create_found_items_total"] == 0
    assert data["summary"]["would_enqueue_notifications_total"] == 0


@pytest.mark.asyncio
async def test_baseline_seen_does_not_create_found_or_update_monitor(route_context):
    app, session, monitor = route_context
    original_last_check_at = monitor.last_check_at
    found_before = await count_rows(session, FoundItem)
    response = await post_baseline(app, "?domain=vinted.pl&dry_run=false")
    await session.refresh(monitor)

    assert response.status_code == 200
    assert await count_rows(session, FoundItem) == found_before == 0
    assert monitor.last_check_at.replace(tzinfo=timezone.utc) == original_last_check_at


@pytest.mark.asyncio
async def test_baseline_seen_does_not_enqueue_notifications_or_send_telegram(route_context):
    app, _, _ = route_context
    with patch(
        "app.scheduler.tasks.send_item_notification",
        side_effect=AssertionError("Telegram must not be called"),
    ) as send_mock:
        response = await post_baseline(app, "?domain=vinted.pl&dry_run=false")

    assert response.status_code == 200
    assert response.json()["side_effects"]["enqueues_notifications"] is False
    send_mock.assert_not_called()


@pytest.mark.asyncio
async def test_baseline_seen_rejects_oversized_before_vinted_calls(route_context):
    app, _, _ = route_context
    with patch("app.web.diagnostics_api_router.VintedClient") as client_class, patch(
        "app.web.diagnostics_api_router.perform_monitor_baseline_seen",
        new_callable=AsyncMock,
    ) as helper:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/diagnostics/monitors/22/baseline-seen-no-notify?max_domains=8"
            )

    assert response.status_code == 200
    data = response.json()
    assert data["safe_error"] == "baseline_seen_request_too_large"
    assert data["side_effects"]["calls_vinted"] is False
    assert data["side_effects"]["writes_seen_items"] is False
    client_class.assert_not_called()
    helper.assert_not_called()


@pytest.mark.asyncio
async def test_baseline_seen_rejects_unselected_domain(route_context):
    app, _, _ = route_context
    with patch("app.web.diagnostics_api_router.VintedClient") as client_class, patch(
        "app.scheduler.dry_run.perform_monitor_dry_run",
        side_effect=ValueError("Domain vinted.de is not selected by this monitor"),
    ):
        client_class.return_value.close = AsyncMock()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/diagnostics/monitors/22/baseline-seen-no-notify?domain=vinted.de"
            )

    assert response.status_code == 400
