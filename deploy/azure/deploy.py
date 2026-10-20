#!/usr/bin/env python3
"""Deploy with Azure CLI authentication. Never print secrets or place them in command arguments."""

import argparse
import base64
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from templates import APP_API, foundation, names, runtime

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("DOCKER_CONFIG", str(ROOT / ".cache/docker"))


def write_json(path, data, private=False):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if private else 0o644
    )
    with os.fdopen(descriptor, "w") as handle:
        json.dump(data, handle, indent=2)
    if private:
        path.chmod(0o600)


def az(*args):
    executable = shutil.which("az") or "/workspace/.tools/azure-cli/bin/az"
    result = subprocess.run(
        [executable, *args, "--only-show-errors", "--output", "json"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        # ARM errors can contain request details. Preserve them privately instead of printing secrets.
        error_path = ROOT / ".cache/azure/last-error.txt"
        error_path.parent.mkdir(parents=True, exist_ok=True)
        error_path.write_text(result.stderr)
        error_path.chmod(0o600)
        raise RuntimeError(
            f"Azure command failed ({' '.join(args[:3])}); details saved privately in {error_path}"
        )
    return json.loads(result.stdout) if result.stdout.strip() else None


def deploy(group, stage, document, directory, parameters=None):
    path = directory / f"{stage}.json"
    write_json(path, document)
    args = [
        "deployment",
        "group",
        "create",
        "--resource-group",
        group,
        "--name",
        f"alexandria-{stage}",
        "--template-file",
        str(path),
    ]
    if parameters:
        args += ["--parameters", "@" + str(parameters)]
    print(f"Deploying {stage}…", flush=True)
    return az(*args)


def grant_operator_secret_access(subscription_id, group, vault):
    # Read only the operator ID from the authenticated CLI token; never log or persist the token.
    access = az(
        "account", "get-access-token", "--resource", "https://management.azure.com/"
    )
    claims = json.loads(
        base64.urlsafe_b64decode(access["accessToken"].split(".")[1] + "===")
    )
    operator_id = claims["oid"]
    account = az("account", "show")
    principal_type = "User" if account["user"]["type"] == "user" else "ServicePrincipal"
    scope = f"/subscriptions/{subscription_id}/resourceGroups/{group}/providers/Microsoft.KeyVault/vaults/{vault}"
    role = "4633458b-17de-408a-b874-0445c86b69e6"
    assignment = str(uuid.uuid5(uuid.NAMESPACE_URL, scope + operator_id + role))
    az(
        "role",
        "assignment",
        "create",
        "--assignee-object-id",
        operator_id,
        "--assignee-principal-type",
        principal_type,
        "--scope",
        scope,
        "--role",
        role,
        "--name",
        assignment,
    )
    print(
        "Granted the signed-in operator access to deployment secrets in Key Vault.",
        flush=True,
    )


def wait_job(resource_id, execution_name):
    for _ in range(180):
        execution = az(
            "rest",
            "--method",
            "get",
            "--url",
            f"{resource_id}/executions/{execution_name}?api-version={APP_API}",
        )
        status = execution["properties"]["status"]
        if status == "Succeeded":
            return
        if status in ("Failed", "Stopped", "Degraded"):
            raise RuntimeError(
                f"Migration/bootstrap job {status}; inspect its Azure execution logs before retrying"
            )
        time.sleep(5)
    raise RuntimeError(
        "Timed out waiting for migration/bootstrap; application rollout was not started"
    )


def wait_health(url):
    for _ in range(60):
        try:
            with urlopen(url + "/api/health", timeout=15) as response:
                health = json.load(response)
            if health.get("status") == "ok" and health.get("queue") == "azure-storage":
                return health
        except (URLError, TimeoutError, ValueError):
            pass
        time.sleep(5)
    raise RuntimeError(
        "The deployment completed but the public API health check did not pass"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--subscription",
        help="Subscription ID; required if the account has multiple subscriptions",
    )
    parser.add_argument("--resource-group", default="alexandria-mvp-westus2")
    parser.add_argument("--location", default="westus2")
    parser.add_argument(
        "--owner-email",
        required=True,
        help="Studio account and Azure budget notifications",
    )
    parser.add_argument(
        "--database-sku",
        choices=["Standard_B1ms", "Standard_B2s"],
        default="Standard_B2s",
    )
    parser.add_argument(
        "--render-only",
        action="store_true",
        help="Render templates locally without calling Azure",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Reuse locally built alexandria images",
    )
    parser.add_argument(
        "--image-tag", help="Reuse a tag already built for both registry images"
    )
    parser.add_argument(
        "--build-method",
        choices=["acr", "local"],
        default="acr",
        help="ACR builds work in Azure Cloud Shell without Docker; local uses Docker",
    )
    args = parser.parse_args()
    if "@" not in args.owner_email or any(c.isspace() for c in args.owner_email):
        parser.error("Provide the owner email address")
    if args.render_only:
        suffix = hashlib.sha256(args.resource_group.encode()).hexdigest()[:10]
        directory = ROOT / ".cache/azure/rendered"
        n = names(suffix)
        for phase, doc in (
            (
                "foundation",
                foundation(n, args.location, args.owner_email, args.database_sku),
            ),
            (
                "migration",
                runtime(n, args.location, args.owner_email, "preview", "migration"),
            ),
            ("app", runtime(n, args.location, args.owner_email, "preview")),
        ):
            write_json(directory / f"{phase}.json", doc)
        print(f"Rendered templates in {directory}; no Azure requests were made.")
        return

    subscriptions = [s for s in az("account", "list") if s.get("state") == "Enabled"]
    if args.subscription:
        matches = [s for s in subscriptions if s["id"] == args.subscription]
    elif len(subscriptions) == 1:
        matches = subscriptions
    else:
        raise RuntimeError(
            "Specify --subscription: there are zero or multiple enabled subscriptions"
        )
    if len(matches) != 1:
        raise RuntimeError(
            "The selected subscription is not available to the authenticated Azure account"
        )
    subscription = matches[0]
    az("account", "set", "--subscription", subscription["id"])
    print(
        f"Azure account: {subscription.get('user', {}).get('name', 'service principal')}"
    )
    print(f"Subscription: {subscription['name']} ({subscription['id']})")
    suffix = hashlib.sha256(
        (subscription["id"] + args.resource_group).encode()
    ).hexdigest()[:10]
    n = names(suffix)
    directory = ROOT / ".cache/azure" / suffix
    parameter_path = directory / "parameters.json"
    group_exists = az("group", "exists", "--name", args.resource_group)
    if group_exists and not parameter_path.exists():
        raise RuntimeError(
            "Resource group already exists but its private deployment parameters are missing. "
            "Recover them from the original deployment workspace; do not regenerate credentials."
        )
    if not parameter_path.exists():
        write_json(
            parameter_path,
            {
                "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
                "contentVersion": "1.0.0.0",
                "parameters": {
                    "databasePassword": {"value": secrets.token_hex(24)},
                    "sessionKey": {"value": secrets.token_hex(32)},
                    "ownerPassword": {"value": secrets.token_urlsafe(24)},
                },
            },
            private=True,
        )
    if not group_exists:
        az(
            "group",
            "create",
            "--name",
            args.resource_group,
            "--location",
            args.location,
            "--tags",
            "application=library-of-alexandria",
            "environment=mvp",
        )
    providers = (
        "Microsoft.App",
        "Microsoft.OperationalInsights",
        "Microsoft.Storage",
        "Microsoft.ContainerRegistry",
        "Microsoft.KeyVault",
        "Microsoft.ManagedIdentity",
        "Microsoft.DBforPostgreSQL",
        "Microsoft.Network",
        "Microsoft.Consumption",
    )
    for provider in providers:
        print(f"Requesting resource provider: {provider}", flush=True)
        az("provider", "register", "--namespace", provider)
    for provider in providers:
        print(f"Waiting for resource provider: {provider}", flush=True)
        az("provider", "register", "--namespace", provider, "--wait")
    deploy(
        args.resource_group,
        "foundation",
        foundation(n, args.location, args.owner_email, args.database_sku),
        directory,
        parameter_path,
    )
    grant_operator_secret_access(subscription["id"], args.resource_group, n["vault"])
    tag = args.image_tag or time.strftime("release-%Y%m%d%H%M%S", time.gmtime())
    if args.image_tag:
        for image in ("backend", "frontend"):
            az(
                "acr",
                "repository",
                "show",
                "--name",
                n["registry"],
                "--image",
                f"{image}:{tag}",
            )
        print(f"Reusing verified registry image tag: {tag}", flush=True)
    elif args.build_method == "acr":
        executable = shutil.which("az") or "/workspace/.tools/azure-cli/bin/az"
        for context, image in (("backend", "backend"), ("frontend", "frontend")):
            subprocess.run(
                [
                    executable,
                    "acr",
                    "build",
                    "--registry",
                    n["registry"],
                    "--image",
                    f"{image}:{tag}",
                    "--file",
                    str(ROOT / context / "Dockerfile.acr"),
                    str(ROOT / context),
                ],
                check=True,
            )
    else:
        if not args.skip_build:
            subprocess.run(
                [sys.executable, "scripts/cloud_build.py"], cwd=ROOT, check=True
            )
        auth = az("acr", "login", "--name", n["registry"], "--expose-token")
        subprocess.run(
            [
                "docker",
                "login",
                auth["loginServer"],
                "--username",
                "00000000-0000-0000-0000-000000000000",
                "--password-stdin",
            ],
            input=auth["accessToken"],
            text=True,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        try:
            for source, target in (
                ("alexandria-backend:local", "backend"),
                ("alexandria-web:local", "frontend"),
            ):
                image = f"{auth['loginServer']}/{target}:{tag}"
                subprocess.run(["docker", "tag", source, image], check=True)
                subprocess.run(["docker", "push", image], check=True)
        finally:
            subprocess.run(
                ["docker", "logout", auth["loginServer"]],
                stdout=subprocess.DEVNULL,
                check=False,
            )
    session_key_url = az(
        "keyvault",
        "secret",
        "show",
        "--vault-name",
        n["vault"],
        "--name",
        "session-key",
        "--query",
        "id",
    )
    deploy(
        args.resource_group,
        "migration",
        runtime(n, args.location, args.owner_email, tag, "migration", session_key_url),
        directory,
    )
    migration_id = f"/subscriptions/{subscription['id']}/resourceGroups/{args.resource_group}/providers/Microsoft.App/jobs/{n['migration']}"
    execution = az(
        "rest",
        "--method",
        "post",
        "--url",
        f"{migration_id}/start?api-version={APP_API}",
    )
    print("Waiting for database migration and initial account creation…", flush=True)
    wait_job(migration_id, execution["name"])
    result = deploy(
        args.resource_group,
        "app",
        runtime(
            n, args.location, args.owner_email, tag, session_key_url=session_key_url
        ),
        directory,
    )
    url = result["properties"]["outputs"]["url"]["value"]
    health = wait_health(url)
    with urlopen(url, timeout=30) as page:
        if page.status != 200:
            raise RuntimeError("Frontend health check failed")
    try:
        urlopen(url + "/api/auth/me", timeout=30)
        raise RuntimeError(
            "Unauthenticated account endpoint unexpectedly accepted access"
        )
    except HTTPError as exc:
        if exc.code != 401:
            raise
    write_json(
        directory / "deployment.json",
        {
            "url": url,
            "resources": n,
            "imageTag": tag,
            "sessionKeySecretId": session_key_url,
            "ownerEmail": args.owner_email,
            "health": health,
        },
    )
    print(f"Deployed and checked: {url}\nStudio login: {args.owner_email}")
    print(
        f"Initial password is stored in Key Vault {n['vault']}, secret owner-password. "
        "Retrieve it securely in Azure Portal; it is never printed here."
    )
    print(
        "AI mode: offline. No paid model calls were made. Budget alerts notify; they do not stop spending."
    )


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        sys.exit(str(exc))
