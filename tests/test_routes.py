from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_home_page_renders():
    response = client.get("/")
    assert response.status_code == 200
    assert "Dota 2" in response.text
    assert "模型设置" in response.text


def test_settings_endpoint_shape():
    response = client.get("/api/llm/settings")
    assert response.status_code == 200
    data = response.json()
    for key in ("provider", "base_url", "model", "providers", "configured"):
        assert key in data
    assert "api_key" not in data
    assert len(data["providers"]) >= 5


def test_missing_match_data_returns_404():
    response = client.get("/api/match/999999999/data")
    assert response.status_code == 404
