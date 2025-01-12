from fastapi.testclient import TestClient
import pytest
from app.core.security import create_access_token
from app.models.user import UserRole

def test_register(client):
    response = client.post(
        "/api/v1/register",
        json={
            "email": "test@example.com",
            "password": "password123",
            "role": UserRole.USER
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "test@example.com"
    assert "id" in data

def test_login(client):
    # Сначала регистрируем пользователя
    client.post(
        "/api/v1/register",
        json={
            "email": "login_test@example.com",
            "password": "password123",
            "role": UserRole.USER
        }
    )
    
    # Пытаемся залогиниться
    response = client.post(
        "/api/v1/login",
        data={
            "username": "login_test@example.com",
            "password": "password123"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer" 