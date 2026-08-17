#!/usr/bin/env python3
"""Diagnose a SharePoint connection before wiring it into the dashboard.

Answers three questions without needing Azure Portal access:

  1. Do these credentials work at all?
  2. **Which Graph permissions were actually granted?** (Files.Read.All,
     Sites.Read.All, Sites.Selected …) — read from the access token itself.
  3. Can this app read the specific workbook we care about?

Why the token: Azure stamps the consented application permissions into the
``roles`` claim of every token it issues. That is the authoritative answer —
more reliable than reading a portal screen, and available to anyone holding the
client secret. The token is NOT signature-verified here; it was just fetched
from Microsoft over TLS and is only being read for diagnostics.

Usage
-----
    python3 scripts/check_sharepoint_access.py

Reads credentials from .streamlit/secrets.toml. To test the credentials from
another dashboard (e.g. the 3PL app) without editing that file:

    python3 scripts/check_sharepoint_access.py \\
        --tenant-id  <tenant> \\
        --client-id  <client> \\
        --client-secret-env AZURE_CLIENT_SECRET \\
        --url "https://…/Group_PL_2026_Upload.xlsx"

Pass the secret via an environment variable, not a command-line argument —
arguments land in your shell history and in `ps` output.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from streamlit_app.data.graph_client import (  # noqa: E402
    GraphError,
    SharePointConfig,
    _acquire_token,
    download_file,
    locate_file,
)

# Application permissions that can read a file in another site's library.
READ_PERMISSIONS = {
    "Files.Read.All": "tenant-wide read of every file",
    "Files.ReadWrite.All": "tenant-wide read AND WRITE of every file",
    "Sites.Read.All": "read every SharePoint site",
    "Sites.ReadWrite.All": "read AND WRITE every SharePoint site",
    "Sites.FullControl.All": "full control of every site",
    "Sites.Selected": "only sites explicitly allow-listed for this app",
}

GREEN, YELLOW, RED, DIM, BOLD, OFF = (
    "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"
)


def _decode_claims(token: str) -> dict:
    """Return the JWT payload claims without verifying the signature."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)  # restore base64 padding
        return json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError, json.JSONDecodeError):
        return {}


def _load_secrets() -> dict:
    path = Path(__file__).resolve().parent.parent / ".streamlit" / "secrets.toml"
    if not path.is_file():
        return {}
    try:
        import tomllib
    except ModuleNotFoundError:  # Python < 3.11
        return {}
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    merged = {k: v for k, v in data.items() if not isinstance(v, dict)}
    merged.update(data.get("files", {}))
    merged.update(data.get("sharepoint", {}))
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id")
    parser.add_argument("--client-id")
    parser.add_argument(
        "--client-secret-env",
        default="AZURE_CLIENT_SECRET",
        help="Name of the env var holding the secret (default: AZURE_CLIENT_SECRET)",
    )
    parser.add_argument("--url", help="SharePoint URL of the workbook to test")
    args = parser.parse_args()

    settings = _load_secrets()
    if args.tenant_id:
        settings["tenant_id"] = args.tenant_id
    if args.client_id:
        settings["client_id"] = args.client_id
    if args.url:
        settings["file_url"] = args.url
    env_secret = os.environ.get(args.client_secret_env)
    if env_secret:
        settings["client_secret"] = env_secret

    config = SharePointConfig.from_mapping(settings)
    if config is None:
        print(f"{RED}✗ No usable configuration.{OFF}")
        print(
            "\n  Need tenant id, client id, client secret, and either a file URL\n"
            "  or hostname + site_path + file_path. Provide them in\n"
            "  .streamlit/secrets.toml or as arguments — see --help."
        )
        return 2

    print(f"\n{BOLD}1. Authenticating{OFF}")
    print(f"   {DIM}tenant {config.tenant_id}  ·  client {config.client_id}{OFF}")
    try:
        token = _acquire_token(config)
    except GraphError as exc:
        print(f"   {RED}✗ {exc}{OFF}\n")
        return 1
    print(f"   {GREEN}✓ Token acquired{OFF}")

    claims = _decode_claims(token)
    app_name = claims.get("app_displayname") or "(name not in token)"
    roles = sorted(claims.get("roles", []))

    print(f"\n{BOLD}2. Granted application permissions{OFF}")
    print(f"   {DIM}app: {app_name}{OFF}")
    if not roles:
        print(f"   {RED}✗ No application permissions in this token.{OFF}")
        print(
            "\n   Either admin consent was never granted, or the permission was\n"
            "   added as Delegated rather than Application. Both are fixed in\n"
            "   Azure → App registrations → API permissions."
        )
        return 1

    relevant = [r for r in roles if r in READ_PERMISSIONS]
    for role in roles:
        note = READ_PERMISSIONS.get(role)
        if note:
            colour = YELLOW if "WRITE" in note or "full control" in note else GREEN
            print(f"   {colour}• {role}{OFF} {DIM}— {note}{OFF}")
        else:
            print(f"   {DIM}• {role}{OFF}")

    print(f"\n{BOLD}3. Reading the workbook{OFF}")
    print(f"   {DIM}{config.web_url}{OFF}")
    try:
        remote = locate_file(config)
    except GraphError as exc:
        print(f"   {RED}✗ {exc}{OFF}")
        if "Sites.Selected" in relevant and len(relevant) == 1:
            print(
                f"\n   {YELLOW}This app uses Sites.Selected, so it can only read sites an\n"
                f"   admin has explicitly allow-listed. The Finance site needs adding.{OFF}"
            )
        return 1

    stamp = (
        remote.last_modified.strftime("%d %b %Y %H:%M UTC")
        if remote.last_modified
        else "unknown"
    )
    size_mb = f"{remote.size / 1_048_576:.1f} MB" if remote.size else "unknown size"
    print(f"   {GREEN}✓ {remote.name}{OFF}")
    print(f"   {DIM}modified {stamp}"
          f"{f' by {remote.modified_by}' if remote.modified_by else ''}  ·  {size_mb}{OFF}")

    try:
        data = download_file(config, remote)
    except GraphError as exc:
        print(f"   {RED}✗ Metadata readable but download failed: {exc}{OFF}")
        return 1
    if not data.startswith(b"PK"):
        print(f"   {YELLOW}⚠ Downloaded {len(data):,} bytes but it is not a valid .xlsx.{OFF}")
        return 1
    print(f"   {GREEN}✓ Downloaded {len(data):,} bytes, valid .xlsx{OFF}")

    print(f"\n{BOLD}Verdict{OFF}")
    if "Sites.Selected" in relevant and len(relevant) == 1:
        print(f"   {GREEN}Works.{OFF} Scoped via Sites.Selected and the Finance site is")
        print("   already allow-listed. Least-privilege — nothing to change.")
    elif relevant:
        widest = relevant[0]
        print(f"   {GREEN}Works.{OFF} These credentials can read the workbook via {BOLD}{widest}{OFF}.")
        print("   Reuse them for the Group P&L dashboard — no new Azure work needed.")
        if any("WRITE" in READ_PERMISSIONS[r] or "full control" in READ_PERMISSIONS[r]
               for r in relevant):
            print(f"\n   {YELLOW}Worth raising:{OFF} this app holds write permissions it does not")
            print("   need. A read-only dashboard should not be able to modify the P&L.")
        elif widest in {"Files.Read.All", "Sites.Read.All"}:
            print(f"\n   {DIM}Note: {widest} covers every site in the tenant. Sites.Selected")
            print(f"   would be tighter, if IT is willing.{OFF}")
    else:
        print(f"   {GREEN}Works{OFF}, via a permission outside the usual read set: {', '.join(roles)}")

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
