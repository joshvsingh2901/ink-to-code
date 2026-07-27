import asyncio

from httpx import ASGITransport, AsyncClient

from app.main import app



async def request(method: str, path: str):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.request(method, path)


def test_health():
    response = asyncio.run(request("GET", "/health"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_transcribe_rejects_missing_multipart_fields_with_structured_error():
    response = asyncio.run(request("POST", "/api/transcribe"))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_validation_error"
