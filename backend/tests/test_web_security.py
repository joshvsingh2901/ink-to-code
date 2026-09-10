import asyncio
import logging
from pathlib import Path
import re

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest

from app.config import Settings, get_settings, validate_web_settings
from app.main import create_app
from app.middleware.request_context import REQUEST_ID_HEADER
from app.services.execution_providers import _docker_base_command


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REQUEST_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def settings(
    *,
    environment: str = "test",
    origins: tuple[str, ...] = ("http://localhost:3000",),
    hsts_enabled: bool = False,
) -> Settings:
    return Settings(
        frontend_origin=origins[0],
        gemini_api_key=None,
        transcription_model="test-model",
        environment=environment,
        rate_limit_enabled=False,
        allowed_frontend_origins=origins,
        hsts_enabled=hsts_enabled,
    )


async def request(app: FastAPI, method: str = "GET", path: str = "/health", **kwargs):
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        return await client.request(method, path, **kwargs)


def test_configured_origin_allowed_without_credentials():
    app = create_app(settings(origins=("https://app.example",)))
    response = asyncio.run(
        request(app, headers={"Origin": "https://app.example"})
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://app.example"
    assert "access-control-allow-credentials" not in response.headers
    assert response.headers["access-control-expose-headers"] == REQUEST_ID_HEADER


def test_random_origin_is_denied():
    app = create_app(settings(origins=("https://app.example",)))
    response = asyncio.run(
        request(app, headers={"Origin": "https://attacker.example"})
    )
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_development_localhost_origin_and_preflight_work():
    app = create_app(settings(environment="development"))
    response = asyncio.run(
        request(
            app,
            "OPTIONS",
            "/api/compile",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert REQUEST_ID_PATTERN.fullmatch(response.headers[REQUEST_ID_HEADER])


@pytest.mark.parametrize(
    "origin",
    ["*", "https://user:password@example.com", "https://example.com/path"],
)
def test_unsafe_cors_origins_are_rejected_at_startup(origin):
    unsafe = settings(environment="production", origins=(origin,))
    with pytest.raises(ValueError, match="explicit HTTP"):
        validate_web_settings(unsafe)
    with pytest.raises(ValueError, match="explicit HTTP"):
        create_app(unsafe)


def test_production_environment_requires_an_explicit_origin(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("FRONTEND_ORIGINS", raising=False)
    monkeypatch.delenv("FRONTEND_ORIGIN", raising=False)
    with pytest.raises(ValueError, match="Production requires"):
        get_settings()


def test_api_security_headers_and_frame_protection_are_present():
    response = asyncio.run(request(create_app(settings())))
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "camera=()" in response.headers["permissions-policy"]
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-frame-options"] == "DENY"


def test_hsts_is_only_emitted_when_explicitly_enabled_in_production():
    production = asyncio.run(
        request(create_app(settings(environment="production", hsts_enabled=True)))
    )
    production_disabled = asyncio.run(
        request(create_app(settings(environment="production")))
    )
    development = asyncio.run(
        request(create_app(settings(environment="development", hsts_enabled=True)))
    )
    assert production.headers["strict-transport-security"].startswith("max-age=")
    assert "strict-transport-security" not in production_disabled.headers
    assert "strict-transport-security" not in development.headers


def test_request_ids_are_server_generated_unique_and_ignore_incoming_values():
    app = create_app(settings())
    first = asyncio.run(
        request(app, headers={REQUEST_ID_HEADER: "attacker\r\ninjected: true"})
    )
    second = asyncio.run(request(app))
    first_id = first.headers[REQUEST_ID_HEADER]
    second_id = second.headers[REQUEST_ID_HEADER]
    assert REQUEST_ID_PATTERN.fullmatch(first_id)
    assert REQUEST_ID_PATTERN.fullmatch(second_id)
    assert first_id != second_id


def test_validation_error_body_contains_response_request_id():
    response = asyncio.run(request(create_app(settings()), "POST", "/api/compile"))
    assert response.status_code == 422
    assert response.json()["request_id"] == response.headers[REQUEST_ID_HEADER]


def test_fastapi_debug_is_disabled_and_public_docs_remain_available():
    app = create_app(settings(environment="production"))
    assert app.debug is False
    assert asyncio.run(request(app, path="/openapi.json")).status_code == 200


def test_unexpected_error_is_safe_correlated_and_cors_readable(caplog):
    app = create_app(
        settings(environment="production", origins=("https://app.example",))
    )
    sensitive_message = "/private/tmp/student.cpp GEMINI_API_KEY=secret-value"

    @app.get("/api/fail")
    async def fail():
        raise RuntimeError(sensitive_message)

    with caplog.at_level(logging.INFO, logger="inktocode.requests"):
        response = asyncio.run(
            request(app, path="/api/fail", headers={"Origin": "https://app.example"})
        )

    body = response.json()
    request_id = response.headers[REQUEST_ID_HEADER]
    assert response.status_code == 500
    assert body == {
        "error": {
            "code": "internal_server_error",
            "message": "An unexpected server error occurred.",
        },
        "request_id": request_id,
    }
    assert response.headers["access-control-allow-origin"] == "https://app.example"
    assert request_id in caplog.text
    assert "request_failed" in caplog.text
    assert "request_complete" in caplog.text
    assert sensitive_message not in response.text
    assert sensitive_message not in caplog.text
    assert "Traceback" not in response.text


def test_request_logging_never_records_json_body(caplog):
    app = create_app(settings(environment="production"))
    sensitive_source = "SOURCE_BODY_SHOULD_NOT_BE_LOGGED"
    sensitive_question = "QUESTION_BODY_SHOULD_NOT_BE_LOGGED"

    @app.post("/api/log-test")
    async def log_test(_payload: dict[str, str]):
        return {"ok": True}

    with caplog.at_level(logging.INFO, logger="inktocode.requests"):
        response = asyncio.run(
            request(
                app,
                "POST",
                "/api/log-test",
                json={"code": sensitive_source, "question": sensitive_question},
            )
        )

    assert response.status_code == 200
    assert "duration_ms=" in caplog.text
    assert sensitive_source not in caplog.text
    assert sensitive_question not in caplog.text


def test_frontend_sources_do_not_reference_backend_secrets():
    frontend_paths = [
        PROJECT_ROOT / "frontend" / "app",
        PROJECT_ROOT / "frontend" / "components",
        PROJECT_ROOT / "frontend" / "lib",
    ]
    files = [
        path
        for root in frontend_paths
        for path in root.rglob("*")
        if path.suffix in {".ts", ".tsx", ".js", ".mjs"}
    ]
    files.extend(
        [
            PROJECT_ROOT / "frontend" / "next.config.ts",
            PROJECT_ROOT / "frontend" / ".env.example",
        ]
    )
    combined = "\n".join(path.read_text(encoding="utf-8") for path in files)
    assert "GEMINI_API_KEY" not in combined
    assert "GEMINI_TEST_GENERATION_MODEL" not in combined
    assert not re.search(r"AIza[0-9A-Za-z_-]{20,}", combined)


def test_backend_env_example_contains_placeholders_only():
    example = (PROJECT_ROOT / "backend" / ".env.example").read_text(
        encoding="utf-8"
    )
    values = dict(
        line.split("=", 1)
        for line in example.splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    assert values["GEMINI_API_KEY"] == ""
    assert not re.search(r"AIza[0-9A-Za-z_-]{20,}|sk-[0-9A-Za-z_-]{20,}", example)


def test_runner_command_does_not_receive_application_environment(tmp_path):
    (tmp_path / "main.cpp").write_text("int main() {}", encoding="utf-8")
    command = _docker_base_command(tmp_path, "inktocode-test", settings())
    assert "--env" not in command
    assert "-e" not in command
    assert all("GEMINI" not in argument for argument in command)
