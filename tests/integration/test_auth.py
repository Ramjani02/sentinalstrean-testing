"""
Integration Tests - Authentication Endpoints
Tests the full HTTP request/response cycle for auth flows.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
class TestRegister:

    async def test_register_success(self, client: AsyncClient):
        response = await client.post("/api/v1/auth/register", json={
            "email": "newuser@test.com",
            "password": "SecurePass1!",
            "full_name": "New User",
            "home_country": "USA",
        })
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "newuser@test.com"
        assert data["full_name"] == "New User"
        assert "id" in data
        assert "hashed_password" not in data  # Must never be exposed

    async def test_register_duplicate_email(self, client: AsyncClient):
        payload = {
            "email": "duplicate@test.com",
            "password": "SecurePass1!",
            "full_name": "User One",
        }
        await client.post("/api/v1/auth/register", json=payload)
        response = await client.post("/api/v1/auth/register", json=payload)
        assert response.status_code == 409

    async def test_register_weak_password_rejected(self, client: AsyncClient):
        response = await client.post("/api/v1/auth/register", json={
            "email": "weakpass@test.com",
            "password": "weak",          # Too short, no uppercase, no digit
            "full_name": "Weak User",
        })
        assert response.status_code == 422

    async def test_register_invalid_email_rejected(self, client: AsyncClient):
        response = await client.post("/api/v1/auth/register", json={
            "email": "not-an-email",
            "password": "SecurePass1!",
            "full_name": "Invalid Email User",
        })
        assert response.status_code == 422


@pytest.mark.asyncio
class TestLogin:

    async def test_login_success_returns_tokens(self, client: AsyncClient, test_user):
        response = await client.post("/api/v1/auth/login", json={
            "email": "testuser@sentinelstream.test",
            "password": "TestPass1!",
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] > 0

    async def test_login_wrong_password(self, client: AsyncClient, test_user):
        response = await client.post("/api/v1/auth/login", json={
            "email": "testuser@sentinelstream.test",
            "password": "WrongPassword1!",
        })
        assert response.status_code == 401

    async def test_login_nonexistent_user(self, client: AsyncClient):
        response = await client.post("/api/v1/auth/login", json={
            "email": "ghost@test.com",
            "password": "SomePass1!",
        })
        assert response.status_code == 401


@pytest.mark.asyncio
class TestGetMe:

    async def test_get_me_authenticated(self, client: AsyncClient, test_user, auth_headers):
        response = await client.get("/api/v1/auth/me", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == test_user.email
        assert data["full_name"] == test_user.full_name

    async def test_get_me_unauthenticated(self, client: AsyncClient):
        response = await client.get("/api/v1/auth/me")
        assert response.status_code == 403  # No credentials provided
