def test_health_endpoint(api_client) -> None:
    response = api_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_read_settings_endpoint(api_client) -> None:
    response = api_client.get("/api/v1/settings")
    assert response.status_code == 200
    payload = response.json()
    assert "groups" in payload
    group_ids = {group["id"] for group in payload["groups"]}
    assert "rag" in group_ids


def test_chat_rejects_missing_message(api_client) -> None:
    response = api_client.post("/api/v1/chat", json={})
    assert response.status_code == 422


def test_documents_formats_endpoint(api_client) -> None:
    response = api_client.get("/api/v1/documents/formats")
    assert response.status_code == 200
    payload = response.json()
    assert "extensions" in payload
    assert ".pdf" in payload["extensions"]
