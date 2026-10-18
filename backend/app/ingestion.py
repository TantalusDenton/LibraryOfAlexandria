"""Bounded ingestion. URL connections are pinned to a validated public IP (including redirects)."""

import http.client
import ipaddress
import re
import socket
import ssl
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from charset_normalizer import from_bytes

from .config import settings


class IngestionError(ValueError):
    pass


def public_destination(url: str):
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise IngestionError("Use a public HTTP(S) URL without embedded credentials")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise IngestionError("Invalid URL port") from exc
    if port not in (80, 443):
        raise IngestionError("Only ports 80 and 443 are permitted")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise IngestionError("Source hostname could not be resolved") from exc
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise IngestionError("Private, loopback, reserved, and mixed public/private hosts are blocked")
    return parsed, port, addresses[0][4][0]


def download(url: str) -> tuple[bytes, str]:
    for _ in range(6):
        parsed, port, address = public_destination(url)
        conn = http.client.HTTPConnection(parsed.hostname, port, timeout=20)
        # Resolve once, validate every address, then connect to that exact address. TLS still verifies host.
        sock = socket.create_connection((address, port), timeout=20)
        try:
            if parsed.scheme == "https":
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=parsed.hostname)
            conn.sock = sock
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            conn.request(
                "GET",
                path,
                headers={
                    "Host": parsed.hostname,
                    "User-Agent": "AlexandriaStudio/0.1",
                    "Accept": "text/plain,text/html",
                    "Accept-Encoding": "identity",
                },
            )
            response = conn.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location:
                    raise IngestionError("Redirect without destination")
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise IngestionError(f"Source returned HTTP {response.status}")
            mime = response.getheader("Content-Type", "").split(";")[0].lower().strip()
            if mime not in ("text/plain", "text/html", "application/xhtml+xml"):
                raise IngestionError("Source must be plain text or HTML")
            if response.getheader("Content-Encoding", "identity") != "identity":
                raise IngestionError("Compressed sources are not accepted")
            limit = settings().max_upload_bytes
            raw = response.read(limit + 1)
            if len(raw) > limit:
                raise IngestionError("Source exceeds the 10 MiB limit")
            return raw, mime
        finally:
            conn.close()
            sock.close()
    raise IngestionError("Too many redirects")


def normalize(raw: bytes, mime="text/plain") -> str:
    if not raw or len(raw) > settings().max_upload_bytes or b"\x00" in raw:
        raise IngestionError("Empty, binary, or oversized manuscript")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        match = from_bytes(raw).best()
        if not match:
            raise IngestionError("Unable to detect text encoding")
        text = str(match)
    if mime != "text/plain":
        soup = BeautifulSoup(text, "html.parser")
        for node in soup(["script", "style", "nav", "header", "footer", "form"]):
            node.decompose()
        text = (soup.find("article") or soup.find("main") or soup).get_text("\n")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.splitlines())
    text = re.sub(r"\n{4,}", "\n\n\n", text).strip()
    # Exclude Gutenberg legal wrappers while keeping original chapter text intact.
    start = re.search(r"\*\*\* START OF (?:THE|THIS) PROJECT GUTENBERG.*?\*\*\*", text, re.I)
    end = re.search(r"\*\*\* END OF (?:THE|THIS) PROJECT GUTENBERG", text, re.I)
    if start:
        text = text[start.end() : end.start() if end else None].strip()
    if len(text) < 30:
        raise IngestionError("Manuscript must contain at least 30 characters")
    return text


HEADING = re.compile(
    r"(?im)^[ \t]*(?:(?:chapter|book|part|act|canto|chapitre|kapitel|cap[ií]tulo)[ \t]+"
    r"(?:[IVXLCDM]+|\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty)"
    r"(?:[ \t]*[.:\-–—][^\n]{0,100})?[ \t]*|"
    r"(?:prologue|epilogue)(?:[ \t]*[:\-–—][^\n]{0,100})?[ \t]*|[IVXLCDM]+[.)]?[ \t]*)$"
)


def detect_chapters(text: str) -> list[dict]:
    matches = list(HEADING.finditer(text))
    # A contents list can repeat chapter headings; short contiguous entries are not chapter bodies.
    matches = [
        m
        for i, m in enumerate(matches)
        if (matches[i + 1].start() if i + 1 < len(matches) else len(text)) - m.end() >= 60
    ]
    boundaries = [(m.start(), m.group().strip()) for m in matches]
    if boundaries and boundaries[0][0] > 300:
        boundaries.insert(0, (0, "Opening"))
    if not boundaries:
        boundaries = [(0, "Section 1")]
        cursor = 16000
        while cursor < len(text):
            split = text.find("\n\n", cursor)
            if split < 0:
                break
            boundaries.append((split + 2, f"Section {len(boundaries) + 1}"))
            cursor = split + 16000
    return [
        dict(
            position=i,
            title=title,
            start_offset=start,
            end_offset=boundaries[i + 1][0] if i + 1 < len(boundaries) else len(text),
        )
        for i, (start, title) in enumerate(boundaries)
    ]


def chunks(text: str, size=12000):
    for start in range(0, len(text), size):
        yield start, text[start : start + size]
