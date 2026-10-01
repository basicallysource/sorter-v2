"""The supervisor serves the UI's static build: the app shell for any page, the
built files with the right headers, nothing from outside the build, and the
restart route only to the UI it serves."""

from __future__ import annotations

import gzip
import http.client
import socket
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import supervisor as sup

SHELL = b"<!doctype html><title>Sorter</title>"
SCRIPT = b"export const app = 1;"
SCRIPT_PATH = "/_app/immutable/entry/app.abc123.js"


class _Supervisor:
    def __init__(self) -> None:
        self.restarts = 0

    def request_restart(self) -> bool:
        self.restarts += 1
        return True


@pytest.fixture
def build(tmp_path: Path) -> Path:
    build = tmp_path / "frontend" / "build"
    (build / "_app" / "immutable" / "entry").mkdir(parents=True)
    (build / "index.html").write_bytes(SHELL)
    (build / "index.html.gz").write_bytes(gzip.compress(SHELL))
    (build / "index.html.br").write_bytes(b"brotli shell")
    (build / SCRIPT_PATH.lstrip("/")).write_bytes(SCRIPT)
    (build / (SCRIPT_PATH.lstrip("/") + ".gz")).write_bytes(gzip.compress(SCRIPT))
    (build / "_app" / "version.json").write_bytes(b'{"version":"1"}')
    (build / "favicon.ico").write_bytes(b"icon")
    (tmp_path / "frontend" / "secret.txt").write_bytes(b"secret")
    return build


@pytest.fixture
def serve():
    servers: list[ThreadingHTTPServer] = []

    def start(build_dir: Path, supervisor: _Supervisor | None = None) -> int:
        server = ThreadingHTTPServer(("127.0.0.1", 0), sup._ui_handler(supervisor or _Supervisor(), build_dir))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return server.server_address[1]

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def _get(port: int, path: str, method: str = "GET", **headers: str) -> tuple[int, dict[str, str], bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request(method, path, headers={k.replace("_", "-"): v for k, v in headers.items()})
        response = conn.getresponse()
        return response.status, {k.lower(): v for k, v in response.getheaders()}, response.read()
    finally:
        conn.close()


def test_every_page_gets_the_shell(build: Path, serve) -> None:
    port = serve(build)
    for path in ("/", "/settings/versions", "/tracked/1234?tab=images", "/settings/"):
        status, headers, body = _get(port, path)
        assert (status, body) == (200, SHELL), path
        assert headers["content-type"] == "text/html"
        assert headers["cache-control"] == "no-cache"


def test_a_missing_built_file_is_a_404_never_the_shell(build: Path, serve) -> None:
    port = serve(build)
    for path in ("/_app/immutable/entry/app.gone.js", "/_app/nothing", "/_app/immutable/"):
        status, _headers, body = _get(port, path)
        assert status == 404, path
        assert body != SHELL


def test_hashed_files_are_kept_for_good_and_the_rest_is_checked(build: Path, serve) -> None:
    port = serve(build)
    status, headers, body = _get(port, SCRIPT_PATH)
    assert (status, body) == (200, SCRIPT)
    assert headers["content-type"] == "text/javascript"
    assert headers["cache-control"] == "public, max-age=31536000, immutable"
    for path in ("/_app/version.json", "/favicon.ico"):
        status, headers, _body = _get(port, path)
        assert status == 200
        assert headers["cache-control"] == "no-cache", path


def test_precompressed_files_follow_accept_encoding(build: Path, serve) -> None:
    port = serve(build)
    _status, headers, body = _get(port, "/", Accept_Encoding="gzip, deflate, br")
    assert (headers["content-encoding"], body) == ("br", b"brotli shell")
    assert headers["content-type"] == "text/html"
    _status, headers, body = _get(port, "/", Accept_Encoding="gzip;q=1.0, deflate")
    assert headers["content-encoding"] == "gzip"
    assert gzip.decompress(body) == SHELL
    _status, headers, body = _get(port, "/")
    assert "content-encoding" not in headers
    assert body == SHELL
    assert headers["vary"] == "Accept-Encoding"
    # No .br beside the script: gzip, the next one the browser takes.
    _status, headers, body = _get(port, SCRIPT_PATH, Accept_Encoding="br, gzip")
    assert headers["content-encoding"] == "gzip"
    assert headers["content-type"] == "text/javascript"
    assert gzip.decompress(body) == SCRIPT


def test_nothing_outside_the_build_is_served(build: Path, serve) -> None:
    (build / "link.txt").symlink_to(build.parent / "secret.txt")
    (build / "_app" / "link.txt").symlink_to(build.parent / "secret.txt")
    port = serve(build)
    for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/..%2fsecret.txt", "//../secret.txt",
                 "/link.txt", "/_app/../../secret.txt", "/nul%00l"):
        status, _headers, body = _get(port, path)
        assert (status, body) == (200, SHELL), path
    for path in ("/_app/link.txt", "/_app/%2e%2e/%2e%2e/secret.txt/"):
        status, _headers, body = _get(port, path)
        assert status in (200, 404), path
        assert b"secret" not in body, path


def test_head_sends_the_headers_alone(build: Path, serve) -> None:
    status, headers, body = _get(serve(build), "/", method="HEAD")
    assert (status, body) == (200, b"")
    assert headers["content-length"] == str(len(SHELL))


def test_without_a_build_every_path_says_how_to_build_it(tmp_path: Path, serve) -> None:
    port = serve(tmp_path / "frontend" / "build")
    for path in ("/", SCRIPT_PATH):
        status, headers, body = _get(port, path)
        assert status == 503
        assert headers["content-type"] == "text/html; charset=utf-8"
        assert b"pnpm install --frozen-lockfile &amp;&amp; pnpm build" in body


def test_only_the_ui_served_here_may_restart_the_backend(build: Path, serve) -> None:
    backend = _Supervisor()
    port = serve(build, backend)
    here = f"http://127.0.0.1:{port}"
    status, _headers, _body = _get(port, sup.RESTART_PATH, method="POST", Origin=here)
    assert status == 202
    assert backend.restarts == 1
    for origin in ("http://attacker.example", f"http://127.0.0.1:{port + 1}", "null", ""):
        status, _headers, _body = _get(port, sup.RESTART_PATH, method="POST", Origin=origin)
        assert status == 403, origin
    status, _headers, _body = _get(port, sup.RESTART_PATH, method="POST")
    assert status == 403
    status, _headers, _body = _get(port, "/api/supervisor/other", method="POST", Origin=here)
    assert status == 404
    assert backend.restarts == 1


def test_a_page_under_another_sites_name_may_not_restart_it(build: Path, serve) -> None:
    # DNS rebinding: another site's page reaching this machine under that
    # site's own name sends an Origin that matches the Host.
    backend = _Supervisor()
    port = serve(build, backend)
    for name in ("attacker.example", "sorter.example.com"):
        status, _headers, _body = _get(
            port, sup.RESTART_PATH, method="POST", Host=f"{name}:{port}", Origin=f"http://{name}:{port}"
        )
        assert status == 403, name
    for name in ("sorter.local", "sorter", "sorter.tail1234.ts.net", "192.168.1.20", "[fe80::1]", "localhost"):
        status, _headers, _body = _get(port, sup.RESTART_PATH, method="POST", Host=name, Origin=f"http://{name}")
        assert status == 202, name
    assert backend.restarts == 6


def test_a_page_loads_its_files_over_one_connection(build: Path, serve) -> None:
    port = serve(build)
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        for path in ("/", SCRIPT_PATH, "/settings"):
            conn.request("GET", path)
            response = conn.getresponse()
            response.read()
            assert response.status == 200
            assert not response.will_close, path
    finally:
        conn.close()


def test_the_ui_takes_its_port_once_it_is_free(build: Path, capsys: pytest.CaptureFixture[str]) -> None:
    holder = socket.socket()
    holder.bind(("0.0.0.0", 0))
    holder.listen()
    port = holder.getsockname()[1]
    bound: list[ThreadingHTTPServer] = []
    waiter = threading.Thread(
        target=lambda: bound.append(sup._bind_ui(port, sup._ui_handler(_Supervisor(), build))), daemon=True
    )
    waiter.start()
    waiter.join(timeout=2.5)
    assert not bound  # still somebody else's
    holder.close()
    waiter.join(timeout=5)
    assert bound
    server = bound[0]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert _get(port, "/")[2] == SHELL
    finally:
        server.shutdown()
        server.server_close()
    assert capsys.readouterr().out.count("cannot serve the UI") == 1
