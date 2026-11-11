"""Skillporter GitHub App Webhook Server (`integrations/github-app/app.py`).

Listens for `pull_request` (`opened`, `synchronize`, `reopened`) webhook events,
runs `generate_ci_report()` on the target repository checkout, and comments an
actionable Markdown report covering:
  * Cross-harness reachability matrix
  * SHA-256 content drift & broken symlinks
  * Duplicate loading warnings
  * 0-100 security risk scores & findings
  * `skillporter.lock` staleness (`lock --check`).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from skillporter.ci_report import generate_ci_report, post_github_pr_comment


def verify_webhook_signature(payload_body: bytes, signature_header: str, secret: str) -> bool:
    """Verify GitHub `X-Hub-Signature-256` HMAC-SHA256 webhook signature."""
    if not secret:
        return True
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), payload_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def handle_pull_request_event(
    event_payload: dict[str, object],
    *,
    workspace_root: Path,
    github_token: str | None = None,
    post_comment: bool = False,
) -> dict[str, object]:
    """Process a GitHub `pull_request` webhook event and generate/post the PR report."""
    action = str(event_payload.get("action", ""))
    pr_obj = event_payload.get("pull_request", {})
    repo_obj = event_payload.get("repository", {})
    pr_number = int(pr_obj.get("number", 0)) if isinstance(pr_obj, dict) else 0
    repo_full = str(repo_obj.get("full_name", "")) if isinstance(repo_obj, dict) else ""

    exit_code, markdown, report_data = generate_ci_report(workspace_root)
    comment_posted = False
    if post_comment and repo_full and pr_number > 0:
        post_github_pr_comment(repo_full, pr_number, markdown, token=github_token)
        comment_posted = True

    return {
        "action": action,
        "repository": repo_full,
        "pr_number": pr_number,
        "exit_code": exit_code,
        "healthy": report_data["healthy"],
        "comment_posted": comment_posted,
        "markdown": markdown,
        "report": report_data,
    }


class GitHubAppHandler(BaseHTTPRequestHandler):
    """Minimal zero-dependency HTTP webhook handler for the Skillporter GitHub App."""

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(min(length, 5 * 1024 * 1024))
        secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
        sig = self.headers.get("X-Hub-Signature-256", "")
        if not verify_webhook_signature(body, sig, secret):
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'{"error": "invalid webhook signature"}')
            return

        event_type = self.headers.get("X-GitHub-Event", "pull_request")
        payload = json.loads(body.decode("utf-8"))
        ws = Path(os.environ.get("SKILLPORTER_APP_WORKSPACE", ".")).resolve()
        if event_type == "pull_request":
            res = handle_pull_request_event(
                payload,
                workspace_root=ws,
                post_comment=bool(os.environ.get("GITHUB_TOKEN")),
            )
        else:
            res = {"ignored_event": event_type}

        out = json.dumps(res).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(out)


def run_server(host: str = "127.0.0.1", port: int = 8080) -> None:
    server = HTTPServer((host, port), GitHubAppHandler)
    server.serve_forever()
