import ast
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from PIL import Image
import pytest
import starlette.formparsers

from app.api import transcription as transcription_api
from app.schemas.transcription import TranscriptionResponse
from app.services.transcription import TranscriptionServiceError


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def png_bytes(*, trailing_bytes: int = 0) -> bytes:
    from io import BytesIO

    buffer = BytesIO()
    Image.new("RGB", (8, 8), color=(18, 52, 86)).save(buffer, format="PNG")
    return buffer.getvalue() + (b"x" * trailing_bytes)


def page_metadata(category: str) -> str:
    return json.dumps(
        [
            {
                "file_id": "page-1.png",
                "order": 1,
                "category": category,
                "source_type": "image",
                "original_filename": "notes.png",
                "original_pdf_page_number": None,
            }
        ]
    )


@asynccontextmanager
async def available_gemini_slot():
    yield


async def post_multipart(app: FastAPI, path: str, *, category: str, content: bytes):
    field = "handwritten_code" if category == "handwritten_code" else "question"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.post(
            path,
            files={
                f"{field}_pages": ("page-1.png", content, "image/png"),
            },
            data={f"{field}_metadata": page_metadata(category)},
        )


@pytest.fixture
def transcription_app(monkeypatch):
    app = FastAPI()
    app.include_router(transcription_api.router)
    monkeypatch.setattr(transcription_api, "gemini_slot", available_gemini_slot)
    return app


def track_multipart_tempfiles(monkeypatch, tmp_path):
    real_spooled_file = starlette.formparsers.SpooledTemporaryFile
    opened = []

    def make_spooled_file(*args, **kwargs):
        kwargs["dir"] = tmp_path
        handle = real_spooled_file(*args, **kwargs)
        opened.append(handle)
        return handle

    monkeypatch.setattr(starlette.formparsers, "SpooledTemporaryFile", make_spooled_file)
    monkeypatch.setattr(starlette.formparsers.MultiPartParser, "spool_max_size", 64)
    return opened


def assert_framework_tempfiles_cleaned(opened, tmp_path):
    assert opened
    assert all(handle.closed for handle in opened)
    assert list(tmp_path.iterdir()) == []


def test_transcribe_success_closes_framework_upload_tempfiles(
    transcription_app, monkeypatch, tmp_path
):
    opened = track_multipart_tempfiles(monkeypatch, tmp_path)
    monkeypatch.setattr(
        transcription_api,
        "transcribe_pages",
        lambda *_args: TranscriptionResponse(
            code="int main() {}",
            overall_confidence=1.0,
            uncertain_regions=[],
            page_count=1,
            model="mock-model",
        ),
    )

    response = asyncio.run(
        post_multipart(
            transcription_app,
            "/api/transcribe",
            category="handwritten_code",
            content=png_bytes(trailing_bytes=256),
        )
    )

    assert response.status_code == 200
    assert response.json()["code"] == "int main() {}"
    assert_framework_tempfiles_cleaned(opened, tmp_path)


def test_parser_failure_closes_framework_upload_tempfiles(
    transcription_app, monkeypatch, tmp_path
):
    opened = track_multipart_tempfiles(monkeypatch, tmp_path)
    response = asyncio.run(
        post_multipart(
            transcription_app,
            "/api/transcribe",
            category="handwritten_code",
            content=b"\x89PNG\r\n\x1a\n" + (b"broken" * 64),
        )
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "malformed_image"
    assert_framework_tempfiles_cleaned(opened, tmp_path)


def test_gemini_failure_closes_framework_upload_tempfiles(
    transcription_app, monkeypatch, tmp_path
):
    opened = track_multipart_tempfiles(monkeypatch, tmp_path)

    def fail_transcription(*_args):
        raise TranscriptionServiceError(
            "transcription_service_unavailable", "Transcription is unavailable.", 503
        )

    monkeypatch.setattr(transcription_api, "transcribe_pages", fail_transcription)
    response = asyncio.run(
        post_multipart(
            transcription_app,
            "/api/transcribe",
            category="handwritten_code",
            content=png_bytes(trailing_bytes=256),
        )
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "transcription_service_unavailable"
    assert_framework_tempfiles_cleaned(opened, tmp_path)


def test_question_transcription_workflow_uses_validated_image_bytes(
    transcription_app, monkeypatch
):
    monkeypatch.setattr(
        transcription_api,
        "transcribe_question_pages",
        lambda pages, _settings: "Question text" if pages[0].content else "",
    )
    response = asyncio.run(
        post_multipart(
            transcription_app,
            "/api/transcribe-question",
            category="question",
            content=png_bytes(),
        )
    )

    assert response.status_code == 200
    assert response.json()["question_text"] == "Question text"


def test_production_python_has_no_shell_or_dynamic_code_execution():
    production_files = list((PROJECT_ROOT / "backend" / "app").rglob("*.py"))
    production_files.extend((PROJECT_ROOT / "runner").rglob("*.py"))
    process_calls = []

    for path in production_files:
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                assert node.func.id not in {"eval", "exec"}, path
            if isinstance(node.func, ast.Attribute):
                owner = node.func.value
                owner_name = owner.id if isinstance(owner, ast.Name) else None
                assert (owner_name, node.func.attr) not in {
                    ("os", "system"),
                    ("os", "popen"),
                    ("asyncio", "create_subprocess_exec"),
                    ("asyncio", "create_subprocess_shell"),
                }, path
                if owner_name == "subprocess" and node.func.attr in {"run", "Popen"}:
                    process_calls.append(path.relative_to(PROJECT_ROOT).as_posix())
                    shell_keywords = [
                        keyword.value
                        for keyword in node.keywords
                        if keyword.arg == "shell"
                    ]
                    assert len(shell_keywords) == 1
                    assert isinstance(shell_keywords[0], ast.Constant)
                    assert shell_keywords[0].value is False

    assert set(process_calls) == {
        "backend/app/services/execution_providers.py",
        "runner/runner.py",
    }
