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
