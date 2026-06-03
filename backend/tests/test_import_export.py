import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import app
from app.models import Monitor, User, UserSession
from app.web.auth import generate_session_token
from app.web.csrf import csrf_token_for_session
from app.web.dependencies import get_db

@pytest.mark.asyncio
async def test_monitor_create_api_parses_url_and_schedules(db_session):
    """Test monitor creation through the API-first route."""
    user = User(username="testuser", is_admin=False)
    user.set_password("pass")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    token = generate_session_token()
    db_session.add(UserSession(user_id=user.id, token=token))
    await db_session.commit()

    class SchedulerStub:
        def __init__(self):
            self.added: list[tuple[int, int]] = []
            self.removed: list[int] = []
            self.updated: list[tuple[int, int]] = []

        def add_monitor(self, monitor_id: int, interval: int) -> None:
            self.added.append((monitor_id, interval))

        def remove_monitor(self, monitor_id: int) -> None:
            self.removed.append(monitor_id)

        def update_monitor(self, monitor_id: int, interval: int) -> None:
            self.updated.append((monitor_id, interval))

        def trigger_now(self, monitor_id: int) -> bool:
            return True

    scheduler = SchedulerStub()
    app.state.scheduler = scheduler
    app.dependency_overrides[get_db] = lambda: db_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("session_token", token)
        response = await client.post(
            "/api/v1/monitors",
            headers={"X-CSRF-Token": csrf_token_for_session(token)},
            json={
                "name": "Nike monitor",
                "url": "https://www.vinted.pl/catalog?search_text=nike",
                "interval_sec": 120,
            },
        )

    assert response.status_code == 200
    result = await db_session.execute(select(Monitor).where(Monitor.user_id == user.id))
    monitors = result.scalars().all()
    assert len(monitors) == 1
    assert "nike" in monitors[0].params_json
    assert scheduler.added == [(monitors[0].id, 120)]
    app.dependency_overrides.clear()
