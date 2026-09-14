"""ingest-url must not become a way into the private network (SSRF)."""

from __future__ import annotations

import http.server
import socket
import threading

import pytest

from module_1_document_processing.pipeline import safe_fetch


@pytest.mark.parametrize(
    "ip",
    ["127.0.0.1", "10.0.0.1", "172.18.0.5", "192.168.1.20", "169.254.169.254", "0.0.0.0", "::1", "fe80::1%eth0", "::ffff:10.0.0.1", "fd00::5"],
)
def test_non_public_addresses_are_refused(ip):
    with pytest.raises(safe_fetch.UnsafeUrlError):
        safe_fetch.require_public_address(ip)


@pytest.mark.parametrize("ip", ["93.184.216.34", "8.8.8.8", "2606:4700:4700::1111"])
def test_public_addresses_are_allowed(ip):
    safe_fetch.require_public_address(ip)


class _Server:
    """A local HTTP server that counts requests and answers with ``responses`` in turn."""

    def __init__(self, *responses: tuple[int, dict[str, str], bytes]) -> None:
        self.requests: list[str] = []
        outer = self
        answers = list(responses)

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                outer.requests.append(self.path)
                status, headers, body = answers.pop(0) if answers else (200, {}, b"hello")
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.httpd.shutdown()


def test_a_page_on_a_private_address_is_never_contacted():
    server = _Server()
    try:
        with pytest.raises(safe_fetch.UnsafeUrlError):
            safe_fetch.fetch_public_url(f"http://127.0.0.1:{server.port}/admin", max_bytes=1000, timeout=5)
        assert server.requests == []  # refused before any request reached it
    finally:
        server.close()


def test_a_hostname_that_resolves_privately_is_refused_without_connecting(monkeypatch):
    monkeypatch.setattr(safe_fetch.socket, "getaddrinfo", lambda host, port, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", port))])

    def no_connections(*args, **kwargs):
        raise AssertionError("connected to a private address")

    monkeypatch.setattr(safe_fetch, "_open_socket", no_connections)
    with pytest.raises(safe_fetch.UnsafeUrlError, match="not on the public internet"):
        safe_fetch.fetch_public_url("http://workspace-service:8083/api/v1/workspaces", max_bytes=1000, timeout=5)


def test_a_public_page_that_redirects_inward_is_refused(monkeypatch):
    # "public.test" stands in for a public site; it answers with a redirect to an internal address.
    server = _Server((302, {"Location": "http://169.254.169.254/latest/meta-data/"}, b""))
    real_getaddrinfo = socket.getaddrinfo
    real_require = safe_fetch.require_public_address

    def resolve(host, port, **kwargs):
        if host == "public.test":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]
        return real_getaddrinfo(host, port, **kwargs)

    def loopback_is_public_for_this_test(ip):
        if ip != "127.0.0.1":
            real_require(ip)

    monkeypatch.setattr(safe_fetch.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(safe_fetch, "require_public_address", loopback_is_public_for_this_test)
    try:
        with pytest.raises(safe_fetch.UnsafeUrlError):
            safe_fetch.fetch_public_url(f"http://public.test:{server.port}/moved", max_bytes=1000, timeout=5)
        assert server.requests == ["/moved"]  # the first hop was fetched; the redirect target never was
    finally:
        server.close()


def test_a_public_page_is_fetched_within_the_size_limit(monkeypatch):
    server = _Server((200, {"Content-Type": "text/html"}, b"<p>" + b"x" * 5000 + b"</p>"))
    monkeypatch.setattr(safe_fetch.socket, "getaddrinfo", lambda host, port, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))])
    real_require = safe_fetch.require_public_address
    monkeypatch.setattr(safe_fetch, "require_public_address", lambda ip: None if ip == "127.0.0.1" else real_require(ip))
    try:
        body = safe_fetch.fetch_public_url(f"http://docs.test:{server.port}/page", max_bytes=100, timeout=5)
        assert body.startswith(b"<p>xx") and len(body) == 100
    finally:
        server.close()


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://10.0.0.5/secrets.txt", "gopher://127.0.0.1:6379/_INFO"])
def test_other_schemes_are_refused(url):
    with pytest.raises(safe_fetch.UnsafeUrlError, match="only http and https"):
        safe_fetch.fetch_public_url(url, max_bytes=1000, timeout=5)
