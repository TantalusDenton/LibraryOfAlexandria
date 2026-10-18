"""Build through an existing managed egress proxy, preserving TLS and avoiding credential output."""

import os
import socket
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

repo = Path(__file__).resolve().parents[1]
os.environ.setdefault("DOCKER_CONFIG", str(repo / ".cache/docker"))
args = ["docker", "build", "--progress=plain"]
if proxy_url := os.environ.get("HTTPS_PROXY"):
    proxy = urlsplit(proxy_url)
    address = socket.getaddrinfo(proxy.hostname, proxy.port or 80, type=socket.SOCK_STREAM)[0][4][0]
    args += ["--network=host", "--add-host", f"{proxy.hostname}:{address}"]
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"):
        if name in os.environ:
            args += ["--build-arg", name]
    if certificate := os.environ.get("CODEX_PROXY_CERT"):
        args += ["--secret", f"id=build_ca,src={certificate}"]
for context, image in (("backend", "alexandria-backend:local"), ("frontend", "alexandria-web:local")):
    subprocess.run([*args, "-t", image, context], cwd=repo, check=True)
