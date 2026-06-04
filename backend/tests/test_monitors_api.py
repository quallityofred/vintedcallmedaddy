import pytest
from httpx import ASGITransport, AsyncClient
from datetime import datetime, timezone
import json

from app.main import app
from app.models import Monitor, User
from app.scraper.url_parser import extract_domains_from_url, parse_vinted_url
from app.web.dependencies import get_db


async def _create_user(db_session, username: str, password: str = "password") -> User:
    user = User(username=username, telegram_bot_token="", telegram_chat_id="")
    user.set_password(password)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _login_user(client: AsyncClient, username: str, password: str = "password") -> str:
    csrf_resp = await client.get("/api/v1/auth/csrf")
    csrf_token = csrf_resp.json()["csrf_token"]
    login_resp = await client.post(
        "/api/v1/auth/login",
        headers={"X-CSRF-Token": csrf_token},
        json={"username": username, "password": password},
    )
    return login_resp.json()["csrf_token"]


def _override_db(db_session) -> None:
    app.dependency_overrides[get_db] = lambda: db_session


@pytest.mark.asyncio
async def test_list_monitors_unauthenticated(db_session):
    _override_db(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/monitors")
        assert response.status_code == 401
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_supported_domains_returns_unique_representatives(db_session):
    _override_db(db_session)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/monitors/domains")

    assert response.status_code == 200
    data = response.json()
    domains = [item["domain"] for item in data]
    assert domains
    assert len(domains) == len(set(domains))
    assert "vinted.fr" in domains
    assert "vinted.de" in domains
    assert "vinted.pl" in domains
    assert "vinted.cz" not in domains
    assert "vinted.sk" not in domains
    assert all(item["host"].startswith("www.") for item in data)
    assert all("label" in item for item in data)

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_monitors_user_scoping(db_session):
    user1 = await _create_user(db_session, "mon_mut_user1")
    user2 = await _create_user(db_session, "mon_mut_user2")
    _override_db(db_session)

    # User 1 monitors
    m1 = Monitor(
        user_id=user1.id,
        name="M1",
        original_url="url1",
        params_json="{}",
        domains_json="[]",
        is_active=True,
    )
    # User 2 monitor
    m2 = Monitor(
        user_id=user2.id,
        name="M2",
        original_url="url2",
        params_json="{}",
        domains_json="[]",
        is_active=True,
    )
    db_session.add_all([m1, m2])
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _login_user(client, "mon_mut_user1")
        response = await client.get("/api/v1/monitors")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "M1"
        assert data[0]["domains"] == []
        detail_response = await client.get(f"/api/v1/monitors/{m1.id}")
        assert detail_response.status_code == 200
        assert detail_response.json()["domains"] == []
        assert "password_hash" not in response.text

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_monitor_success(db_session):
    await _create_user(db_session, "mon_mut_user3")
    _override_db(db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        csrf_token = await _login_user(client, "mon_mut_user3")
        
        payload = {
            "name": "New Monitor",
            "url": "https://www.vinted.fr/catalog?search_text=nike",
            "interval_sec": 300,
            "domains": ["vinted.fr"]
        }
        response = await client.post(
            "/api/v1/monitors",
            headers={"X-CSRF-Token": csrf_token},
            json=payload
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "New Monitor"
        assert data["interval_sec"] == 300
        assert data["is_active"] is True
        assert data["domains"] == ["vinted.fr"]

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_monitor_rejects_empty_domains(db_session):
    await _create_user(db_session, "mon_empty_domains")
    _override_db(db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        csrf_token = await _login_user(client, "mon_empty_domains")
        response = await client.post(
            "/api/v1/monitors",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "name": "Empty Domains",
                "url": "https://www.vinted.fr/catalog?search_text=nike",
                "domains": [],
            },
        )

    assert response.status_code == 400
    assert "target domain" in response.json()["detail"].lower()
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_monitor_rejects_unknown_domain(db_session):
    await _create_user(db_session, "mon_unknown_domain")
    _override_db(db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        csrf_token = await _login_user(client, "mon_unknown_domain")
        response = await client.post(
            "/api/v1/monitors",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "name": "Unknown Domain",
                "url": "https://www.vinted.fr/catalog?search_text=nike",
                "domains": ["vinted.example"],
            },
        )

    assert response.status_code == 400
    assert "unsupported target domain" in response.json()["detail"].lower()
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_monitor_alias_url_normalizes_to_representative(db_session):
    user = await _create_user(db_session, "mon_alias_url")
    _override_db(db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        csrf_token = await _login_user(client, "mon_alias_url")
        response = await client.post(
            "/api/v1/monitors",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "name": "Alias URL",
                "url": "https://www.vinted.cz/catalog?search_text=nike",
                "interval_sec": 120,
            },
        )

    assert response.status_code == 200
    assert response.json()["domains"] == ["vinted.pl"]
    monitor = await db_session.get(Monitor, response.json()["id"])
    assert monitor is not None
    assert monitor.user_id == user.id
    assert json.loads(monitor.domains_json) == ["vinted.pl"]
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_monitor_validates_domains(db_session):
    user = await _create_user(db_session, "mon_update_domains")
    _override_db(db_session)

    monitor = Monitor(
        user_id=user.id,
        name="Update Domains",
        original_url="https://www.vinted.fr/catalog?search_text=nike",
        params_json="{}",
        domains_json=json.dumps(["vinted.fr"]),
        is_active=True,
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        csrf_token = await _login_user(client, "mon_update_domains")
        empty_response = await client.patch(
            f"/api/v1/monitors/{monitor.id}",
            headers={"X-CSRF-Token": csrf_token},
            json={"domains": []},
        )
        unknown_response = await client.patch(
            f"/api/v1/monitors/{monitor.id}",
            headers={"X-CSRF-Token": csrf_token},
            json={"domains": ["vinted.cz"]},
        )
        valid_response = await client.patch(
            f"/api/v1/monitors/{monitor.id}",
            headers={"X-CSRF-Token": csrf_token},
            json={"domains": ["www.vinted.de", "vinted.fr", "vinted.fr"]},
        )

    assert empty_response.status_code == 400
    assert unknown_response.status_code == 400
    assert valid_response.status_code == 200
    assert valid_response.json()["domains"] == ["vinted.de", "vinted.fr"]
    await db_session.refresh(monitor)
    assert json.loads(monitor.domains_json) == ["vinted.de", "vinted.fr"]
    app.dependency_overrides.clear()


def test_parse_vinted_url_removes_unstable_params_and_preserves_stable_params():
    params = parse_vinted_url(
        "https://www.vinted.pl/catalog?"
        "catalog[]=1231&brand_ids[]=324572&page=1&time=1780516803&"
        "search_id=abc&utm_source=test&order=newest_first"
    )

    assert params["catalog[]"] == [1231]
    assert params["brand_ids[]"] == [324572]
    assert params["order"] == "newest_first"
    assert "page" not in params
    assert "time" not in params
    assert "search_id" not in params
    assert "utm_source" not in params


def test_extract_domains_from_url_resolves_alias_to_representative():
    assert extract_domains_from_url("https://www.vinted.sk/catalog?search_text=nike") == ["vinted.pl"]


@pytest.mark.asyncio
async def test_update_monitor_owner_only(db_session):
    user1 = await _create_user(db_session, "mon_mut_user4")
    user2 = await _create_user(db_session, "mon_mut_user5")
    _override_db(db_session)

    m1 = Monitor(
        user_id=user1.id,
        name="Old Name",
        original_url="url1",
        params_json="{}",
        domains_json="[]",
        is_active=True,
    )
    db_session.add(m1)
    await db_session.commit()
    await db_session.refresh(m1)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # User 2 tries to update User 1's monitor
        csrf_token2 = await _login_user(client, "mon_mut_user5")
        response = await client.patch(
            f"/api/v1/monitors/{m1.id}",
            headers={"X-CSRF-Token": csrf_token2},
            json={"name": "Stolen Name"}
        )
        assert response.status_code == 404

        # User 1 updates own monitor
        async with AsyncClient(transport=transport, base_url="http://test") as client1:
            csrf_token1 = await _login_user(client1, "mon_mut_user4")
            response = await client1.patch(
                f"/api/v1/monitors/{m1.id}",
                headers={"X-CSRF-Token": csrf_token1},
                json={"name": "New Name", "is_active": False}
            )
            assert response.status_code == 200
            assert response.json()["name"] == "New Name"
            assert response.json()["is_active"] is False
            assert response.json()["domains"] == []

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_delete_monitor_owner_only(db_session):
    user1 = await _create_user(db_session, "mon_mut_user6")
    user2 = await _create_user(db_session, "mon_mut_user7")
    _override_db(db_session)

    m1 = Monitor(
        user_id=user1.id,
        name="M1",
        original_url="url1",
        params_json="{}",
        domains_json="[]",
        is_active=True,
    )
    db_session.add(m1)
    await db_session.commit()
    await db_session.refresh(m1)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # User 2 tries to delete User 1's monitor
        csrf_token2 = await _login_user(client, "mon_mut_user7")
        response = await client.delete(
            f"/api/v1/monitors/{m1.id}",
            headers={"X-CSRF-Token": csrf_token2}
        )
        assert response.status_code == 404

        # User 1 deletes own monitor
        async with AsyncClient(transport=transport, base_url="http://test") as client1:
            csrf_token1 = await _login_user(client1, "mon_mut_user6")
            response = await client1.delete(
                f"/api/v1/monitors/{m1.id}",
                headers={"X-CSRF-Token": csrf_token1}
            )
            assert response.status_code == 204

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_bulk_delete_monitors(db_session):
    user1 = await _create_user(db_session, "mon_mut_user8")
    user2 = await _create_user(db_session, "mon_mut_user9")
    _override_db(db_session)

    m1 = Monitor(user_id=user1.id, name="M1", original_url="u1", params_json="{}", domains_json="[]")
    m2 = Monitor(user_id=user1.id, name="M2", original_url="u2", params_json="{}", domains_json="[]")
    m3 = Monitor(user_id=user2.id, name="M3", original_url="u3", params_json="{}", domains_json="[]")
    db_session.add_all([m1, m2, m3])
    await db_session.commit()
    await db_session.refresh(m1)
    await db_session.refresh(m2)
    await db_session.refresh(m3)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        csrf_token = await _login_user(client, "mon_mut_user8")
        
        # Try to delete m1, m2 (own) and m3 (someone else's)
        payload = {"monitor_ids": [m1.id, m2.id, m3.id, 9999]}
        response = await client.post(
            "/api/v1/monitors/bulk-delete",
            headers={"X-CSRF-Token": csrf_token},
            json=payload
        )
        assert response.status_code == 200
        data = response.json()
        assert data["deleted_count"] == 2
        assert set(data["not_found_or_forbidden_ids"]) == {m3.id, 9999}

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_pause_resume_monitor(db_session):
    user = await _create_user(db_session, "mon_mut_user10")
    _override_db(db_session)

    m1 = Monitor(user_id=user.id, name="M1", original_url="u1", params_json="{}", domains_json="[]", is_active=True)
    db_session.add(m1)
    await db_session.commit()
    await db_session.refresh(m1)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        csrf_token = await _login_user(client, "mon_mut_user10")
        
        # Pause
        response = await client.post(f"/api/v1/monitors/{m1.id}/pause", headers={"X-CSRF-Token": csrf_token})
        assert response.status_code == 200
        assert response.json()["is_active"] is False
        assert response.json()["domains"] == []
        
        # Resume
        response = await client.post(f"/api/v1/monitors/{m1.id}/resume", headers={"X-CSRF-Token": csrf_token})
        assert response.status_code == 200
        assert response.json()["is_active"] is True
        assert response.json()["domains"] == []

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_debug_monitor_masked_url_regression(db_session):
    _override_db(db_session)
    user = await _create_user(db_session, "debug_reg_user")
    user.cf_worker_url = "https://worker-secret-token-12345678"
    user.cf_worker_mode = "manual"
    db_session.add(user)
    
    m1 = Monitor(user_id=user.id, name="Debug M1", original_url="u1", params_json="{}", domains_json="[]")
    db_session.add(m1)
    await db_session.commit()
    await db_session.refresh(user)
    await db_session.refresh(m1)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        csrf_token = await _login_user(client, "debug_reg_user")
        response = await client.get(f"/api/v1/monitors/{m1.id}/debug")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify mask_secret works and no raw URL is leaked
        assert data["cf_worker"]["configured"] is True
        assert data["cf_worker"]["mode"] == "manual"
        assert data["cf_worker"]["url_masked"] is not None
        # mask_secret("...12345678", visible=8) -> "******12345678"
        assert data["cf_worker"]["url_masked"] == "******12345678"
        assert user.cf_worker_url not in response.text
        
    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_debug_monitor_missing_worker_url(db_session):
    _override_db(db_session)
    user = await _create_user(db_session, "debug_no_worker")
    user.cf_worker_url = ""
    db_session.add(user)
    
    m1 = Monitor(user_id=user.id, name="Debug M2", original_url="u1", params_json="{}", domains_json="[]")
    db_session.add(m1)
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _login_user(client, "debug_no_worker")
        response = await client.get(f"/api/v1/monitors/{m1.id}/debug")
        
        assert response.status_code == 200
        data = response.json()
        assert data["cf_worker"]["configured"] is False
        assert data["cf_worker"]["url_masked"] is None
        
    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_debug_monitor_mode_normalization(db_session):
    _override_db(db_session)
    user = await _create_user(db_session, "debug_mode_norm")
    # Simulate invalid mode in DB
    user.cf_worker_mode = "invalid_mode"
    db_session.add(user)
    
    m1 = Monitor(user_id=user.id, name="Debug M3", original_url="u1", params_json="{}", domains_json="[]")
    db_session.add(m1)
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _login_user(client, "debug_mode_norm")
        response = await client.get(f"/api/v1/monitors/{m1.id}/debug")
        
        assert response.status_code == 200
        data = response.json()
        # Should normalize to "auto"
        assert data["cf_worker"]["mode"] == "auto"
        
    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_debug_monitor_scoping_and_auth(db_session):
    _override_db(db_session)
    user1 = await _create_user(db_session, "debug_scope_u1")
    user2 = await _create_user(db_session, "debug_scope_u2")
    
    m1 = Monitor(user_id=user1.id, name="M1", original_url="u1", params_json="{}", domains_json="[]")
    db_session.add(m1)
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Unauthenticated -> 401
        resp = await client.get(f"/api/v1/monitors/{m1.id}/debug")
        assert resp.status_code == 401
        
        # 2. Other user -> 404
        await _login_user(client, "debug_scope_u2")
        resp = await client.get(f"/api/v1/monitors/{m1.id}/debug")
        assert resp.status_code == 404
        
        # 3. Non-existent -> 404
        resp = await client.get("/api/v1/monitors/99999/debug")
        assert resp.status_code == 404
        
    app.dependency_overrides.clear()
