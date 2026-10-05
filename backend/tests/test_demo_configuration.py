import asyncio
import hashlib
import json
from io import BytesIO

from httpx import ASGITransport, AsyncClient
from PIL import Image

from app.api import transcription as transcription_api
from app.config import Settings
from app.main import app
from app.schemas.transcription import TranscriptionResponse
from app.services import transcription as transcription_service


def _image_bytes(color: tuple[int, int, int] = (18, 52, 86)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (8, 8), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


DEMO_IMAGE = _image_bytes()
OTHER_IMAGE = _image_bytes((90, 80, 70))


def test_demo_transcription_fixture_is_exactly_pinned():
    assert transcription_service.DEMO_TRANSCRIPTION_IMAGE_SHA256 == (
        "05894ddc5232ae6476439b5d36a61018547354cc4058778e12044d06fc328a91"
    )
    assert transcription_service.DEMO_TRANSCRIPTION_CODE == (
        "int findMax (int a, int b) {\n"
        "    int maxValue;\n"
        "    if (c > b) {\n"
        "        maxValue = a; }\n"
        "    else {\n"
        "        maxvalue = b;\n"
        "    }\n"
        "    retum MaXVALUE;"
    )


def _settings(*, enabled: bool) -> Settings:
    return Settings(
        frontend_origin="http://localhost:3000",
        gemini_api_key="unused-test-key",
        transcription_model="test-model",
        environment="test",
        rate_limit_enabled=False,
        enable_demo_transcription_fast_path=enabled,
        demo_transcription_delay_seconds=25,
    )


def _metadata(file_ids: list[str], category: str) -> str:
    return json.dumps([
        {
            "file_id": file_id,
            "order": index,
            "category": category,
            "source_type": "image",
            "original_filename": file_id,
            "original_pdf_page_number": None,
        }
        for index, file_id in enumerate(file_ids, start=1)
    ])


async def _post_transcription(
    code_images: list[bytes], *, question_image: bytes | None = None
):
    code_ids = [f"code-{index}.png" for index in range(1, len(code_images) + 1)]
    files = [
        ("handwritten_code_pages", (file_id, content, "image/png"))
        for file_id, content in zip(code_ids, code_images, strict=True)
    ]
    data = {"handwritten_code_metadata": _metadata(code_ids, "handwritten_code")}
    if question_image is not None:
        files.append(
            ("question_pages", ("question-1.png", question_image, "image/png"))
        )
        data["question_metadata"] = _metadata(["question-1.png"], "question")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.post("/api/transcribe", files=files, data=data)


def test_exact_validated_demo_image_waits_without_calling_gemini(
    monkeypatch, caplog,
):
    digest = hashlib.sha256(DEMO_IMAGE).hexdigest()
    delays: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)

    async def unexpected_threadpool(*_args, **_kwargs):
        raise AssertionError("The exact demo image must not call Gemini")

    monkeypatch.setattr(
        transcription_service, "DEMO_TRANSCRIPTION_IMAGE_SHA256", digest
    )
    monkeypatch.setattr(transcription_api, "get_settings", lambda: _settings(enabled=True))
    monkeypatch.setattr(transcription_api.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(transcription_api, "run_in_threadpool", unexpected_threadpool)

    with caplog.at_level("INFO"):
        response = asyncio.run(
            _post_transcription([DEMO_IMAGE], question_image=OTHER_IMAGE)
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == transcription_service.DEMO_TRANSCRIPTION_CODE
    assert payload["code"].endswith("retum MaXVALUE;")
    assert payload["page_count"] == 1
    assert payload["model"] == "demo-precomputed-two-pass"
    assert delays == [25]
    assert digest not in caplog.text


def test_upload_validation_runs_before_demo_match(monkeypatch):
    called = False

    def unexpected_match(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("Invalid uploads must not reach demo matching")

    monkeypatch.setattr(transcription_api, "get_settings", lambda: _settings(enabled=True))
    monkeypatch.setattr(
        transcription_api, "demo_transcription_for_pages", unexpected_match
    )

    response = asyncio.run(_post_transcription([b"not an image"]))

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "upload_content_mismatch"
    assert called is False


def test_non_demo_cases_keep_the_existing_transcription_path(monkeypatch):
    calls: list[tuple[int, int]] = []

    def fake_transcribe(*_args, **_kwargs):
        raise AssertionError("run_in_threadpool should receive this function")

    async def fake_threadpool(function, code_pages, question_pages, _settings):
        assert function is fake_transcribe
        calls.append((len(code_pages), len(question_pages)))
        return TranscriptionResponse(
            code="verified Gemini result",
            overall_confidence=0.8,
            uncertain_regions=[],
            page_count=len(code_pages),
            model="test-model",
        )

    monkeypatch.setattr(
        transcription_service,
        "DEMO_TRANSCRIPTION_IMAGE_SHA256",
        hashlib.sha256(DEMO_IMAGE).hexdigest(),
    )
    monkeypatch.setattr(transcription_api, "transcribe_pages", fake_transcribe)
    monkeypatch.setattr(transcription_api, "run_in_threadpool", fake_threadpool)

    monkeypatch.setattr(transcription_api, "get_settings", lambda: _settings(enabled=False))
    disabled = asyncio.run(_post_transcription([DEMO_IMAGE]))
    monkeypatch.setattr(transcription_api, "get_settings", lambda: _settings(enabled=True))
    different = asyncio.run(_post_transcription([OTHER_IMAGE]))
    multiple = asyncio.run(_post_transcription([DEMO_IMAGE, DEMO_IMAGE]))

    assert disabled.json()["code"] == "verified Gemini result"
    assert different.json()["code"] == "verified Gemini result"
    assert multiple.json()["code"] == "verified Gemini result"
    assert calls == [(1, 0), (1, 0), (2, 0)]
