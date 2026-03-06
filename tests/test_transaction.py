import pytest
from httpx import AsyncClient
from app.main import app

@pytest.mark.asyncio
async def test_transaction():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.post("/transaction", json={
            "amount": 100,
            "location": "NY"
        })
    assert response.status_code == 200
