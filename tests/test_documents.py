import pytest
from fastapi.testclient import TestClient
from app.models.user import UserRole
import os

@pytest.fixture
def manager_token(client):
    # Регистрируем менеджера
    response = client.post(
        "/api/v1/register",
        json={
            "email": "manager@example.com",
            "password": "password123",
            "role": UserRole.MANAGER
        }
    )
    # Логинимся
    response = client.post(
        "/api/v1/login",
        data={
            "username": "manager@example.com",
            "password": "password123"
        }
    )
    return response.json()["access_token"]

def test_create_document(client, manager_token):
    # Создаем тестовый файл
    test_file_path = "test_document.pdf"
    with open(test_file_path, "wb") as f:
        f.write(b"Test content")
    
    try:
        response = client.post(
            "/api/v1/documents/",
            headers={"Authorization": f"Bearer {manager_token}"},
            files={
                "file": ("test.pdf", open(test_file_path, "rb"), "application/pdf")
            },
            data={"title": "Test Document"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Test Document"
        assert data["file_type"] == ".pdf"
    finally:
        # Удаляем тестовый файл
        if os.path.exists(test_file_path):
            os.remove(test_file_path)

def test_read_documents(client, manager_token):
    response = client.get(
        "/api/v1/documents/",
        headers={"Authorization": f"Bearer {manager_token}"}
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list) 