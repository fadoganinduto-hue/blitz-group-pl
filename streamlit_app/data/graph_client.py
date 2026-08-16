"""Microsoft Graph client — read a workbook straight from SharePoint.

Uses the OAuth2 **client credentials** flow: the app authenticates as itself, not
as a signed-in person, so a scheduled refresh or a hosted deployment works with
nobody logged in.

Deliberately built on ``requests`` alone rather than MSAL. The client-credentials
flow is a single POST, and every network call in this file is auditable by a
finance team that has to trust where its P&L numbers come from.

Configuration lives in ``.streamlit/secrets.toml`` (never committed):

    [sharepoint]
    tenant_id     = "..."
    client_id     = "..."
    client_secret = "..."
    hostname      = "61nngljuq69wkvzlaiog9kkphca.sharepoint.com"
    site_path     = "/sites/Finance"
    file_path     = "Shared Documents/Group PL/Group_PL_2026_Upload.xlsx"

``file_path`` is relative to the site's default document library and DOES include
the "Shared Documents" segment as shown in the SharePoint web URL.
"""

from __future__ import annotations

import time
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import requests

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
LOGIN_ROOT = "https://login.microsoftonline.com"
SCOPE = "https://graph.microsoft.com/.default"

# Network timeouts (connect, read). A hung dashboard is worse than a failed one.
TIMEOUT: tuple[int, int] = (10, 60)

# Refresh the token this many seconds before it actually expires.
TOKEN_SKEW_SECONDS = 120


class GraphError(RuntimeError):
    """A Graph call failed, with an explanation aimed at whoever has to fix it."""


@dataclass(frozen=True)
class SharePointConfig:
    """Everything needed to locate one workbook in SharePoint."""

    tenant_id: str
    client_id: str
    client_secret: str = field(repr=False)  # never let a debug print leak this
    hostname: str
    site_path: str
    file_path: str

    @property
    def web_url(self) -> str:
        """Best-effort browser URL, for showing provenance in the UI."""
        return f"https://{self.hostname}{self.site_path}/{self.file_path}"

    @classmethod
    def from_mapping(cls, data: Any) -> "SharePointConfig | None":
        """Build from a secrets mapping, or return None if incomplete."""
        if not data:
            return None
        required = (
            "tenant_id", "client_id", "client_secret",
            "hostname", "site_path", "file_path",
        )
        try:
            values = {key: str(data[key]).strip() for key in required}
        except (KeyError, TypeError):
            return None
        if any(not v or v.startswith("your-") for v in values.values()):
            return None
        # A malformed hostname cannot move the request off graph.microsoft.com,
        # but it can silently target the wrong SharePoint site.
        if not re.fullmatch(r"[A-Za-z0-9.-]+", values["hostname"]):
            return None
        # Normalise: site_path leading slash, file_path no leading slash.
        values["site_path"] = "/" + values["site_path"].strip("/")
        values["file_path"] = values["file_path"].lstrip("/")
        return cls(**values)


@dataclass
class RemoteFile:
    """Metadata for a workbook that lives in SharePoint."""

    name: str
    drive_id: str
    item_id: str
    last_modified: datetime | None
    size: int | None
    etag: str
    web_url: str
    modified_by: str | None = None


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

_token_cache: dict[str, tuple[str, float]] = {}


def _acquire_token(config: SharePointConfig) -> str:
    """Return a bearer token, reusing a cached one until it nears expiry."""
    cache_key = f"{config.tenant_id}:{config.client_id}"
    cached = _token_cache.get(cache_key)
    if cached and cached[1] - TOKEN_SKEW_SECONDS > time.time():
        return cached[0]

    url = f"{LOGIN_ROOT}/{config.tenant_id}/oauth2/v2.0/token"
    try:
        response = requests.post(
            url,
            data={
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "scope": SCOPE,
                "grant_type": "client_credentials",
            },
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise GraphError(
            "Could not reach Microsoft sign-in. Check the network connection "
            f"and that the tenant ID is correct. ({type(exc).__name__})"
        ) from exc

    if response.status_code != 200:
        raise GraphError(_explain_token_failure(response))

    payload = _json(response, "sign-in")
    token = payload.get("access_token")
    if not token:
        raise GraphError("Microsoft returned no access token.")

    expires_in = float(payload.get("expires_in", 3600))
    _token_cache[cache_key] = (token, time.time() + expires_in)
    return str(token)


def _explain_token_failure(response: requests.Response) -> str:
    """Turn an Azure error code into something actionable."""
    try:
        body = response.json()
        code = str(body.get("error", ""))
        description = str(body.get("error_description", ""))
    except ValueError:
        code, description = "", response.text[:300]

    if "AADSTS7000215" in description:
        return (
            "Invalid client secret. The secret VALUE was likely copied wrong, or "
            "it has expired — Azure shows the value only once at creation, and "
            "the Secret ID is not the value."
        )
    if "AADSTS700016" in description or code == "unauthorized_client":
        return (
            "The application was not found in this tenant. Check that client_id "
            "and tenant_id both come from the same app registration."
        )
    if "AADSTS90002" in description:
        return "Tenant not found. Check the tenant_id (Directory ID) in secrets."
    return f"Microsoft sign-in failed ({response.status_code}). {description[:300]}"


def _json(response: requests.Response, what: str) -> dict:
    """Parse a Graph JSON body, converting a non-JSON reply into a GraphError.

    A captive portal or proxy returning an HTML page with status 200 would
    otherwise surface as a raw JSONDecodeError traceback in the browser.
    """
    try:
        payload = response.json()
    except ValueError as exc:
        raise GraphError(
            f"Microsoft returned a non-JSON response during {what}. This usually "
            "means a proxy or captive portal intercepted the request."
        ) from exc
    if not isinstance(payload, dict):
        raise GraphError(f"Unexpected response shape during {what}.")
    return payload


def _get(url: str, token: str, **kwargs: Any) -> requests.Response:
    headers = {"Authorization": f"Bearer {token}"}
    headers.update(kwargs.pop("headers", {}))
    try:
        return requests.get(url, headers=headers, timeout=TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        raise GraphError(f"Graph request failed: {type(exc).__name__}") from exc


def _explain_graph_failure(response: requests.Response, what: str) -> str:
    if response.status_code == 403:
        return (
            f"Access denied reading {what}. The app registration most likely has "
            "Sites.Read.All granted but ADMIN CONSENT has not been clicked, or the "
            "permission was added as Delegated instead of Application."
        )
    if response.status_code == 401:
        return f"Not authorised reading {what}. The token was rejected — check the client secret."
    if response.status_code == 404:
        return (
            f"Not found: {what}. Check hostname, site_path and file_path against "
            "the SharePoint web URL. file_path is relative to the site and does "
            "include the 'Shared Documents' segment."
        )
    return f"Graph error {response.status_code} reading {what}: {response.text[:200]}"


# ---------------------------------------------------------------------------
# Locating and reading the workbook
# ---------------------------------------------------------------------------

def _parse_timestamp(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(
            timezone.utc
        )
    except ValueError:
        return None


def locate_file(config: SharePointConfig) -> RemoteFile:
    """Resolve the configured site + path to a concrete drive item."""
    token = _acquire_token(config)

    site_url = f"{GRAPH_ROOT}/sites/{config.hostname}:{quote(config.site_path, safe='/')}"
    site_response = _get(site_url, token)
    if site_response.status_code != 200:
        raise GraphError(
            _explain_graph_failure(site_response, f"site '{config.site_path}'")
        )
    site_id = _json(site_response, "site lookup").get("id")
    if not site_id:
        raise GraphError(
            f"Graph returned no site id for '{config.site_path}'. Check site_path "
            "against the SharePoint URL (it looks like /sites/<name>)."
        )

    # The file path in a SharePoint web URL includes the library name
    # ("Shared Documents"), but Graph's drive root is already inside it.
    drive_relative = config.file_path
    for library_prefix in ("Shared Documents/", "Documents/", "Shared%20Documents/"):
        if drive_relative.startswith(library_prefix):
            drive_relative = drive_relative[len(library_prefix):]
            break

    encoded = quote(drive_relative)
    item_url = f"{GRAPH_ROOT}/sites/{site_id}/drive/root:/{encoded}"
    item_response = _get(item_url, token)
    if item_response.status_code != 200:
        raise GraphError(
            _explain_graph_failure(item_response, f"file '{config.file_path}'")
        )

    item = _json(item_response, "file lookup")
    modified_by = None
    try:
        modified_by = item["lastModifiedBy"]["user"]["displayName"]
    except (KeyError, TypeError):
        pass

    try:
        size = int(item["size"]) if item.get("size") is not None else None
    except (TypeError, ValueError):
        size = None

    return RemoteFile(
        name=str(item.get("name", "workbook.xlsx")),
        drive_id=str(item.get("parentReference", {}).get("driveId", "")),
        item_id=str(item.get("id", "")),
        last_modified=_parse_timestamp(item.get("lastModifiedDateTime")),
        size=size,
        # eTag changes on every save — the natural cache key.
        etag=str(item.get("eTag") or item.get("cTag") or ""),
        web_url=str(item.get("webUrl", config.web_url)),
        modified_by=modified_by,
    )


def download_file(config: SharePointConfig, remote: RemoteFile) -> bytes:
    """Download the workbook's bytes."""
    token = _acquire_token(config)
    url = f"{GRAPH_ROOT}/drives/{remote.drive_id}/items/{remote.item_id}/content"
    response = _get(url, token, allow_redirects=True)
    if response.status_code != 200:
        raise GraphError(_explain_graph_failure(response, f"contents of '{remote.name}'"))
    return response.content


def check_connection(config: SharePointConfig) -> tuple[bool, str]:
    """Probe the configuration and return (ok, human-readable message)."""
    try:
        remote = locate_file(config)
    except GraphError as exc:
        return False, str(exc)
    stamp = (
        remote.last_modified.strftime("%d %b %Y %H:%M UTC")
        if remote.last_modified
        else "unknown"
    )
    return True, f"Connected. '{remote.name}', last modified {stamp}."
