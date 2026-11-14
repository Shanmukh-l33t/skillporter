"""TDD regression tests for AI-review bundle redaction/HTTPS (B11) and registry catalog HTTP hardening (B12)."""

from __future__ import annotations

import http.server
import json
import socket
import threading
from pathlib import Path

import pytest

from skillporter.ai_review import AIReviewError, collect_skill_review_bundle, run_optional_ai_security_review
from skillporter.cli import main
from skillporter.registry import load_catalog

# Assemble test tokens dynamically so secret scanners never flag source literals.
FAKE_AWS_ID = "".join(("AK", "IA", "IOSFODNN7EXAMPLE"))
FAKE_GH_PAT = "".join(("ghp_", "0123456789abcdefghij0123456789"))
FAKE_OAI_KEY = "-".join(("sk", "proj", "0123456789abcdef0123456789"))
FAKE_PEM = "\n".join(
    (
        "-----BEGIN " + "OPENSSH PRIVATE KEY-----",
        "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQ==",
        "-----END " + "OPENSSH PRIVATE KEY-----",
    )
)
FAKE_ENV_VAL = "-".join(("db", "secret", "99887766"))


def _skill_with_secrets(base: Path, name: str = "sec-skill") -> Path:
    sdir = base / name
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Safe formatting helper. Use when formatting text.\n---\n\n"
        f"# {name}\n\nNormal markdown instructions. Example inline key {FAKE_AWS_ID} and {FAKE_GH_PAT}.\n",
        encoding="utf-8",
    )
    (sdir / ".env").write_text(f"DB_PASS={FAKE_ENV_VAL}\n", encoding="utf-8")
    (sdir / ".env.production").write_text(f"PROD_PASS={FAKE_ENV_VAL}\n", encoding="utf-8")
    (sdir / "id_rsa").write_text(FAKE_PEM + "\n", encoding="utf-8")
    (sdir / "cert.key").write_text(FAKE_PEM + "\n", encoding="utf-8")
    (sdir / "notes.txt").write_text(f"Embedded key block:\n{FAKE_PEM}\n", encoding="utf-8")
    return sdir


class _FakeAIServer:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length).decode("utf-8", errors="replace")
                outer.requests.append(
                    {
                        "path": self.path,
                        "auth": self.headers.get("Authorization"),
                        "body": raw,
                    }
                )
                reply = {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {"verdict": "APPROVE", "summary": "Clean skill.", "findings": []}
                                )
                            }
                        }
                    ]
                }
                payload = json.dumps(reply).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args: object) -> None:
                return

        self._httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


@pytest.fixture
def fake_ai():
    srv = _FakeAIServer()
    try:
        yield srv
    finally:
        srv.close()


def test_b11_ai_bundle_excludes_sensitive_files_and_redacts_inline_secrets(tmp_path, monkeypatch, fake_ai):
    sdir = _skill_with_secrets(tmp_path)
    bundle_text, _, withheld_direct = collect_skill_review_bundle(sdir)
    assert ".env" in withheld_direct and "id_rsa" in withheld_direct
    assert "Normal markdown instructions." in bundle_text
    assert FAKE_ENV_VAL not in bundle_text
    assert FAKE_AWS_ID not in bundle_text
    assert FAKE_GH_PAT not in bundle_text
    assert "OPENSSH PRIVATE KEY" not in bundle_text
    assert "=== FILE: .env ===" not in bundle_text
    assert "=== FILE: id_rsa ===" not in bundle_text

    # Without --yes-send: zero network bytes sent, consent prompt names withheld files
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_OAI_KEY)
    monkeypatch.setenv("SKILLPORTER_AI_BASE_URL", f"http://127.0.0.1:{fake_ai.port}/v1")
    with pytest.raises(AIReviewError) as ei:
        run_optional_ai_security_review(sdir, model_spec="openai:gpt-4o-mini", authorize_send=False)
    assert fake_ai.requests == []
    msg = str(ei.value)
    assert ".env" in msg and "id_rsa" in msg

    # With --yes-send over loopback: request succeeds, zero secrets transmitted in body
    res = run_optional_ai_security_review(sdir, model_spec="openai:gpt-4o-mini", authorize_send=True)
    assert len(fake_ai.requests) == 1
    sent_body = str(fake_ai.requests[0]["body"])
    assert "Normal markdown instructions." in sent_body
    assert FAKE_ENV_VAL not in sent_body
    assert FAKE_AWS_ID not in sent_body
    assert FAKE_GH_PAT not in sent_body
    assert "OPENSSH PRIVATE KEY" not in sent_body
    withheld_res = list(res["withheld_sensitive_files"])  # type: ignore[arg-type]
    assert ".env" in withheld_res
    assert "id_rsa" in withheld_res


@pytest.mark.parametrize(
    "bad_base",
    [
        "http://198.51.100.10:8080/v1",
        "http://evil.example.com/v1",
        "HTTP://evil.example.com/v1",
        "ftp://evil.example.com/v1",
        "https://" + "user" + ":" + "secretpw99" + "@api.example.com/v1",
    ],
)
def test_b11_ai_review_rejects_non_loopback_http_and_bad_urls_before_connect(tmp_path, monkeypatch, bad_base):
    sdir = _skill_with_secrets(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_OAI_KEY)
    monkeypatch.setenv("SKILLPORTER_AI_BASE_URL", bad_base)

    def forbid_connect(*args, **kwargs):
        raise AssertionError("socket connection must not be attempted for rejected AI base URL")

    monkeypatch.setattr(socket, "create_connection", forbid_connect)
    with pytest.raises(AIReviewError) as ei:
        run_optional_ai_security_review(sdir, model_spec="openai:gpt-4o-mini", authorize_send=True)
    err_txt = str(ei.value)
    assert FAKE_OAI_KEY not in err_txt
    assert "secretpw99" not in err_txt


def test_b11_ai_review_rejects_newline_in_api_key_without_echoing_it(tmp_path, monkeypatch, fake_ai):
    sdir = _skill_with_secrets(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", f"{FAKE_OAI_KEY}\r\nX-Hdr: 1")
    monkeypatch.setenv("SKILLPORTER_AI_BASE_URL", f"http://127.0.0.1:{fake_ai.port}/v1")
    with pytest.raises(AIReviewError) as ei:
        run_optional_ai_security_review(sdir, model_spec="openai:gpt-4o-mini", authorize_send=True)
    assert FAKE_OAI_KEY not in str(ei.value)
    assert fake_ai.requests == []


def test_b12_load_catalog_rejects_cleartext_non_loopback_http_and_keeps_json_clean(monkeypatch, capsys):
    def forbid_connect(*args, **kwargs):
        raise AssertionError("socket connection must not be attempted for non-loopback HTTP catalog")

    monkeypatch.setattr(socket, "create_connection", forbid_connect)
    pkgs = load_catalog("http://198.51.100.42:9000/index.json")
    cap = capsys.readouterr()
    assert pkgs  # falls back to seed catalog
    assert "warning:" in cap.err.lower()
    assert "cleartext" in cap.err.lower() or "https" in cap.err.lower()

    # CLI `skillporter search --json` keeps stdout strictly valid JSON while warning on stderr
    monkeypatch.setenv("SKILLPORTER_REGISTRY_URL", "http://198.51.100.42:9000/index.json")
    assert main(["search", "pdf", "--json"]) == 0
    cli_cap = capsys.readouterr()
    parsed = json.loads(cli_cap.out)
    assert isinstance(parsed, (list, dict))
    assert "warning:" in cli_cap.err.lower()


def test_b12_load_catalog_allows_loopback_http_and_blocks_http_downgrade_redirect():
    redirect_target = "http://198.51.100.99:9999/injected.json"

    class CatHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/redir":
                self.send_response(302)
                self.send_header("Location", redirect_target)
                self.end_headers()
                return
            body = json.dumps(
                {
                    "packages": [
                        {
                            "slug": "localtest/loopback-skill",
                            "source": "https://github.com/example/loopback-skill",
                            "description": "Served from loopback test server",
                        }
                    ]
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            return

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), CatHandler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        pkgs_ok = load_catalog(f"http://127.0.0.1:{port}/index.json")
        assert any(p.slug == "localtest/loopback-skill" for p in pkgs_ok)

        pkgs_redir = load_catalog(f"http://127.0.0.1:{port}/redir")
        assert not any(p.slug == "localtest/loopback-skill" for p in pkgs_redir)
    finally:
        httpd.shutdown()
        httpd.server_close()
