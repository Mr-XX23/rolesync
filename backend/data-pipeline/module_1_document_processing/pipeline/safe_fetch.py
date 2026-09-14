"""Fetching a web page for the knowledge vault without reaching into the private network.

``ingest-url`` fetches the address it is given from inside the platform network. Unchecked, anyone
who can add a page to the vault (a rep, or an AI agent that read hostile text in an email or on a
web page) could point it at an internal service, workspace-service or a cloud metadata endpoint,
and the answer would be stored in the vault where it can be read back.

So every connection this opener makes goes only to public addresses: the hostname is resolved
here, private answers are dropped before any packet is sent, and the socket connects to the
address that was checked (a DNS answer can't change in between). Redirects open their
connections through the same path, so a public page that redirects inward is refused too, and
schemes other than http and https are refused outright.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import urllib.parse
import urllib.request
from typing import Any


NOT_PUBLIC_MESSAGE = "Only pages on the public internet can be added to the knowledge vault."


class UnsafeUrlError(ValueError):
    """The address leads somewhere other than the public internet."""


def require_public_address(ip: str) -> None:
    """Refuse loopback, private, link-local, reserved and other non-global addresses."""
    try:
        address = ipaddress.ip_address(ip.split("%", 1)[0])  # an IPv6 zone id isn't part of the address
    except ValueError as exc:
        raise UnsafeUrlError(f"'{ip}' is not an IP address") from exc
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:  # ::ffff:10.0.0.1 is 10.0.0.1
        address = mapped
    if not address.is_global:
        raise UnsafeUrlError("that address is not on the public internet")


def _open_socket(family: int, sockaddr: tuple[Any, ...], timeout: Any, source_address: Any) -> socket.socket:
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
            sock.settimeout(timeout)
        if source_address:
            sock.bind(source_address)
        sock.connect(sockaddr)
        return sock
    except BaseException:
        sock.close()
        raise


def _public_connection(address: tuple[str, int], timeout: Any = socket._GLOBAL_DEFAULT_TIMEOUT, source_address: Any = None, *args: Any, **kwargs: Any) -> socket.socket:
    """``socket.create_connection``, but only ever to the public addresses a host resolves to."""
    host, port = address
    checked = []
    for family, _, _, _, sockaddr in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM):
        try:
            require_public_address(str(sockaddr[0]))
        except UnsafeUrlError:
            continue
        checked.append((family, sockaddr))
    if not checked:
        raise UnsafeUrlError(f"'{host}' is not on the public internet")
    last_error: OSError | None = None
    for family, sockaddr in checked:  # connect to exactly the address that was checked
        try:
            return _open_socket(family, sockaddr, timeout, source_address)
        except OSError as exc:
            last_error = exc
    raise last_error if last_error is not None else OSError(f"could not connect to {host}")


class _PublicHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._create_connection = _public_connection


class _PublicHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._create_connection = _public_connection  # TLS still verifies the certificate against the hostname


class _PublicHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req: urllib.request.Request) -> Any:
        return self.do_open(_PublicHTTPConnection, req)


class _PublicHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req: urllib.request.Request) -> Any:
        options: dict[str, Any] = {"context": self._context}
        if hasattr(self, "_check_hostname"):  # Python 3.11 passes this separately; 3.12 folded it into the context
            options["check_hostname"] = self._check_hostname
        return self.do_open(_PublicHTTPSConnection, req, **options)


class _NoFTPHandler(urllib.request.FTPHandler):
    def ftp_open(self, req: urllib.request.Request) -> Any:
        raise UnsafeUrlError("only http and https pages can be added")


class _NoFileHandler(urllib.request.FileHandler):
    def file_open(self, req: urllib.request.Request) -> Any:
        raise UnsafeUrlError("only http and https pages can be added")


# No proxy from the environment: a proxy would make the connection on our behalf, unchecked.
_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), _PublicHTTPHandler(), _PublicHTTPSHandler(), _NoFTPHandler(), _NoFileHandler()
)


def fetch_public_url(url: str, *, max_bytes: int, timeout: float, headers: dict[str, str] | None = None) -> bytes:
    """At most ``max_bytes`` of the page at ``url``; raises ``UnsafeUrlError`` for anything not public."""
    if urllib.parse.urlsplit(url).scheme.lower() not in ("http", "https"):
        raise UnsafeUrlError("only http and https pages can be added")
    request = urllib.request.Request(url, headers=headers or {})
    with _OPENER.open(request, timeout=timeout) as response:
        return response.read(max_bytes + 1)[:max_bytes]
