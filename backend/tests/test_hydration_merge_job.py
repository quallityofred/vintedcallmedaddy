import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from app.web.diagnostics_api_router import router
from app.models import User
from app.web.api_dependencies import require_api_user
from app.web.dependencies import get_db
from app.scheduler.diagnostics import registry

def create_test_app():
    app = FastAPI()
    app.include_router(router)
    return app

@pytest.mark.asyncio
async def test_hydration_ssr_merge_job_start_route_returns_job_id():
    app = create_test_app()
    mock_user = User(id=1, username="admin")
    mock_user.token = "secret"
    app.dependency_overrides[require_api_user] = lambda: mock_user

    mock_db = AsyncMock()
    mock_monitor = MagicMock()
    mock_monitor.id = 22
    mock_monitor.user_id = 1
    mock_monitor.domains_json = '["vinted.pl", "vinted.fr"]'
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_monitor
    mock_db.execute = AsyncMock(return_value=mock_result)
    app.dependency_overrides[get_db] = lambda: mock_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch(
            "app.scheduler.tasks.run_hydration_ssr_merge_job",
            new_callable=AsyncMock,
        ) as mock_task:
            response = await client.post(
                f"/api/v1/diagnostics/monitors/{mock_monitor.id}/jobs/hydration-ssr-photo-merge"
                "?max_domains=2&max_items_per_domain=50&sample_limit=4",
                headers={"Authorization": "Bearer secret"}
            )
            assert response.status_code == 200, response.json()
            data = response.json()
            assert "job_id" in data
            assert data["status"] == "running"
            assert data["source"] == "hydration_with_ssr_photos"
            mock_task.assert_awaited_once_with(
                22,
                data["job_id"],
                target_domain=None,
                max_domains=2,
                max_items_per_domain=50,
                sample_limit=4,
            )


def _completed_result(job_id: str) -> dict:
    return {
        "job_id": job_id,
        "status": "completed",
        "source": "hydration_with_ssr_photos",
        "started_at": "2026-06-08T00:00:00+00:00",
        "completed_at": "2026-06-08T00:00:01+00:00",
        "duration_ms_total": 1000,
        "summary": {"domains_processed_total": 1, "html_fetch_count_total": 1},
        "counts_by_domain": {"vinted.pl": {"hydration_items": 1}},
        "samples_by_domain": {"vinted.pl": [{"item_id": "123"}]},
        "errors_by_domain": {},
        "side_effects": {
            "reads_database": True,
            "calls_vinted": True,
            "writes_seen_items": False,
            "writes_found_items": False,
            "enqueues_notifications": False,
            "sends_telegram": False,
            "runs_scheduler_check": False,
        },
    }


@pytest.mark.asyncio
async def test_hydration_ssr_merge_job_status_route_returns_full_completed_shape():
    app = create_test_app()
    user = User(id=1, username="admin")
    app.dependency_overrides[require_api_user] = lambda: user
    db = AsyncMock()
    db_result = MagicMock()
    db_result.scalar_one_or_none.return_value = 22
    db.execute.return_value = db_result
    app.dependency_overrides[get_db] = lambda: db
    job_id = "merge_22_completed"
    await registry.start_job(job_id, 22, "hydration_with_ssr_photos")
    await registry.complete_job(job_id, _completed_result(job_id))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/diagnostics/monitors/22/jobs/{job_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["source"] == "hydration_with_ssr_photos"
    assert data["summary"]["domains_processed_total"] == 1
    assert "vinted.pl" in data["counts_by_domain"]
    assert "vinted.pl" in data["samples_by_domain"]
    assert data["errors_by_domain"] == {}
    assert data["side_effects"]["writes_found_items"] is False


@pytest.mark.asyncio
async def test_hydration_ssr_merge_job_status_not_old_last_check_snapshot():
    app = create_test_app()
    user = User(id=1, username="admin")
    app.dependency_overrides[require_api_user] = lambda: user
    db = AsyncMock()
    db_result = MagicMock()
    db_result.scalar_one_or_none.return_value = 22
    db.execute.return_value = db_result
    app.dependency_overrides[get_db] = lambda: db
    job_id = "merge_22_shape"
    await registry.start_job(job_id, 22, "hydration_with_ssr_photos")
    await registry.complete_job(job_id, _completed_result(job_id))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        data = (await client.get(f"/api/v1/diagnostics/monitors/22/jobs/{job_id}")).json()

    assert "result" not in data
    assert "last_check_source" not in data
    assert "items_found_count_by_domain" not in data
    assert "domains_processed" not in data
    assert {"summary", "counts_by_domain", "samples_by_domain", "errors_by_domain"} <= data.keys()


@pytest.mark.asyncio
async def test_hydration_ssr_merge_job_failed_status_is_structured_and_safe():
    app = create_test_app()
    user = User(id=1, username="admin")
    app.dependency_overrides[require_api_user] = lambda: user
    db = AsyncMock()
    db_result = MagicMock()
    db_result.scalar_one_or_none.return_value = 22
    db.execute.return_value = db_result
    app.dependency_overrides[get_db] = lambda: db
    job_id = "merge_22_failed"
    await registry.start_job(job_id, 22, "hydration_with_ssr_photos")
    await registry.fail_job(job_id, "RuntimeError")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/diagnostics/monitors/22/jobs/{job_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert data["safe_error"] == "RuntimeError"
    assert data["errors_by_domain"] == {"__global__": "RuntimeError"}
    assert data["summary"] == {}
    assert data["side_effects"]["writes_seen_items"] is False
    assert data["side_effects"]["writes_found_items"] is False
    assert data["side_effects"]["enqueues_notifications"] is False
    assert data["side_effects"]["sends_telegram"] is False


@pytest.mark.asyncio
async def test_hydration_ssr_merge_job_unknown_job_id_returns_structured_404():
    app = create_test_app()
    app.dependency_overrides[require_api_user] = lambda: User(id=1, username="admin")
    db = AsyncMock()
    db_result = MagicMock()
    db_result.scalar_one_or_none.return_value = 22
    db.execute.return_value = db_result
    app.dependency_overrides[get_db] = lambda: db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/diagnostics/monitors/22/jobs/merge_22_unknown"
        )

    assert response.status_code == 404
    assert response.json() == {
        "job_id": "merge_22_unknown",
        "status": "not_found",
        "safe_error": "diagnostic_job_not_found",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", [
    ("POST", "/api/v1/diagnostics/monitors/22/jobs/hydration-ssr-photo-merge"),
    ("GET", "/api/v1/diagnostics/monitors/22/jobs/merge_22_unknown"),
])
async def test_hydration_ssr_merge_job_routes_auth_required(method, path):
    app = create_test_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.request(method, path)

    assert response.status_code == 401
