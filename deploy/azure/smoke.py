"""Run offline hosted acceptance checks with credentials retained only in process memory."""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from deploy import ROOT, az, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "state", type=Path, help="Path to the non-secret deployment.json metadata"
    )
    args = parser.parse_args()
    state = json.loads(args.state.read_text())
    password = az(
        "keyvault",
        "secret",
        "show",
        "--vault-name",
        state["resources"]["vault"],
        "--name",
        "owner-password",
        "--query",
        "value",
    )
    env = dict(
        os.environ,
        STUDIO_URL=state["url"],
        STUDIO_EMAIL=state["ownerEmail"],
        STUDIO_PASSWORD=password,
    )
    print(
        "Running hosted offline publishing acceptance test; credentials are not logged.",
        flush=True,
    )
    result = subprocess.run(
        ["npm", "run", "test:e2e"],
        cwd=ROOT / "frontend",
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout + "\n" + result.stderr
    output = output.replace(password, "[REDACTED]")
    output = re.sub(
        r"alexandria_session=[A-Za-z0-9._-]+", "alexandria_session=[REDACTED]", output
    )
    output = re.sub(
        r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[REDACTED_TOKEN]", output
    )
    log = args.state.parent / "hosted-browser.log"
    log.write_text(output)
    log.chmod(0o600)
    print(output[-8000:], flush=True)
    write_json(
        args.state.parent / "hosted-browser.json",
        {"passed": result.returncode == 0, "url": state["url"], "log": str(log)},
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
