import asyncio

from fastapi import FastAPI, File, UploadFile
from httpx import ASGITransport, AsyncClient

from app.middleware.body_limit import RequestBodyLimitMiddleware


def make_app(max_bytes: int) -> FastAPI:
    test_app = FastAPI()

    @test_app.post("/json")
    async def json_endpoint(payload: dict[str, str]):
        return payload

    @test_app.post("/upload")
    async def upload_endpoint(file: UploadFile = File()):
        return {"size": len(await file.read())}

    test_app.add_middleware(RequestBodyLimitMiddleware, max_bytes=max_bytes)
    return test_app


def test_normal_json_body_is_accepted():
    async def request():
        async with AsyncClient(
            transport=ASGITransport(app=make_app(100)), base_url="http://test"
        ) as client:
            return await client.post("/json", json={"value": "small"})

    response = asyncio.run(request())
    assert response.status_code == 200
    assert response.json() == {"value": "small"}


def test_content_length_over_limit_is_rejected_early():
    async def request():
        async with AsyncClient(
            transport=ASGITransport(app=make_app(10)), base_url="http://test"
        ) as client:
            return await client.post(
                "/json",
                content=b"{}",
                headers={"Content-Length": "11", "Content-Type": "application/json"},
            )

    response = asyncio.run(request())
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_body_too_large"


def test_streamed_body_without_content_length_is_rejected():
    async def chunks():
        yield b'{"value":"'
        yield b"x" * 20
        yield b'"}'

    async def request():
        async with AsyncClient(
            transport=ASGITransport(app=make_app(20)), base_url="http://test"
        ) as client:
            return await client.post(
                "/json", content=chunks(), headers={"Content-Type": "application/json"}
            )

    response = asyncio.run(request())
    assert response.status_code == 413


def test_understated_content_length_cannot_bypass_stream_limit():
    async def chunks():
        yield b"x" * 30

    async def request():
        async with AsyncClient(
            transport=ASGITransport(app=make_app(20)), base_url="http://test"
        ) as client:
            return await client.post(
                "/json",
                content=chunks(),
                headers={"Content-Length": "1", "Content-Type": "application/json"},
            )

    response = asyncio.run(request())
    assert response.status_code == 413


def test_normal_multipart_upload_is_accepted():
    async def request():
        async with AsyncClient(
            transport=ASGITransport(app=make_app(1024)), base_url="http://test"
        ) as client:
            return await client.post(
                "/upload", files={"file": ("page.png", b"image", "image/png")}
            )

    response = asyncio.run(request())
    assert response.status_code == 200
    assert response.json() == {"size": 5}
