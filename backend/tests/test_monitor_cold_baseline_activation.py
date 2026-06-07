from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base, Monitor, SeenItem, User
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
            is_active=False,
            last_check_at=None,
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

async def post_start_with_baseline(
    app: FastAPI,
    monitor_id: int = 22,
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
                f"/api/v1/diagnostics/monitors/{monitor_id}/start-with-baseline{query}"
            )

async def count_rows(session: AsyncSession, model) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)

@pytest.mark.asyncio
async def test_cold_baseline_activate_after_true_activates_monitor_after_success(route_context):
    app, session, monitor = route_context
    # This monitor has 1 domain in its JSON, so it covers all domains
    assert monitor.is_active is False
    
    response = await post_start_with_baseline(app, monitor_id=monitor.id, query="?domain=vinted.pl&dry_run=false&activate_after=true")

    assert response.status_code == 200
    data = response.json()
    assert data["monitor_activated"] is True
    assert data["summary"]["created_seen_items_total"] == 2
    
    await session.refresh(monitor)
    assert monitor.is_active is True
    assert monitor.last_check_at is not None

@pytest.mark.asyncio
async def test_start_with_baseline_rejects_activate_after_for_partial_multidomain_baseline(tmp_path):
    # Need a multi-domain monitor
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'multi.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        user = User(id=1, username="u", password_hash="h", password_salt="s")
        monitor = Monitor(
            id=33, user_id=1, name="Multi", original_url="u", params_json="{}",
            domains_json='["vinted.fr", "vinted.de"]', is_active=False
        )
        session.add_all([user, monitor])
        await session.commit()
        app = create_test_app()
        app.dependency_overrides[require_api_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: session

        # Request only 1 domain of 2, with activation
        response = await post_start_with_baseline(app, monitor_id=monitor.id, query="?domain=vinted.fr&dry_run=false&activate_after=true")
        
        assert response.status_code == 400
        assert response.json()["reason"] == "partial_baseline_activation_not_allowed"
        
        await session.refresh(monitor)
        assert monitor.is_active is False
    await engine.dispose()
