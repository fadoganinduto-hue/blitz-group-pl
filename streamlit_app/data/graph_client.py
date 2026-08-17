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

import base64
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
    # Address the file EITHER by a pasted SharePoint URL (file_url) OR by
    # hostname + site_path + file_path. The URL form matches the house
    # convention used by the 3PL dashboard: copy the browser address bar or a
    # "Copy link" share URL and paste it. The path form is more explicit and
    # survives a share-link being revoked.
    file_url: str = ""
    hostname: str = ""
    site_path: str = ""
    file_path: str = ""

    @property
    def addresses_by_url(self) -> bool:
        return bool(self.file_url)

    @property
    def web_url(self) -> str:
        """Best-effort browser URL, for showing provenance in the UI."""
        if self.file_url:
            return self.file_url
        return f"https://{self.hostname}{self.site_path}/{self.file_path}"

    @property
    def share_token(self) -> str:
        """Graph's /shares addressing: base64url of the URL, prefixed 'u!'."""
        encoded = base64.urlsafe_b64encode(self.file_url.encode()).decode().rstrip("=")
        return f"u!{encoded}"

    @classmethod
    def from_mapping(cls, data: Any) -> "SharePointConfig | None":
        """Build from a secrets mapping, or return None if incomplete.

        Accepts both the house naming used by the existing dashboards
        (AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET, flat at the
        top level) and the nested [sharepoint] form, so one set of credentials
        can serve every Blitz Streamlit app.
        """
        if not data:
            return None

        def pick(*keys: str) -> str:
            for key in keys:
                try:
                    value = data[key]
                except (KeyError, TypeError):
                    continue
                if value:
                    return str(value).strip()
            return ""

        creds = {
            "tenant_id": pick("tenant_id", "AZURE_TENANT_ID"),
            "client_id": pick("client_id", "AZURE_CLIENT_ID"),
            "client_secret": pick("client_secret", "AZURE_CLIENT_SECRET"),
        }
        if any(not v or v.startswith("your-") for v in creds.values()):
            return None

        # NB: deliberately not "path" or "mode" — those belong to [workbook]
        # and must never be mistaken for a SharePoint URL.
        file_url = pick("file_url", "url", "GROUP_PL", "FILE_URL")
        if file_url:
            if not file_url.lower().startswith("https://"):
                return None
            return cls(**creds, file_url=file_url)

        hostname = pick("hostname")
        site_path = pick("site_path")
        file_path = pick("file_path")
        if not (hostname and site_path and file_path):
            return None
        if any(v.startswith("your-") for v in (hostname, site_path, file_path)):
            return None
        # A malformed hostname cannot move the request off graph.microsoft.com,
        # but it can silently target the wrong SharePoint site.
        if not re.fullmatch(r"[A-Za-z0-9.-]+", hostname):
            return None
        return cls(
            **creds,
            hostname=hostname,
            site_path="/" + site_path.strip("/"),
            file_path=file_path.lstrip("/"),
        )


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
            f"Not found: {what}. If you configured file_url, re-copy it from the "
            "browser address bar or the file's Copy-link menu. If you configured "
            "hostname/site_path/file_path, check them against the SharePoint web "
            "URL — file_path is relative to the site and does include the "
            "'Shared Documents' segment."
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


def _remote_from_item(item: dict, config: SharePointConfig) -> RemoteFile:
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


def _locate_by_url(config: SharePointConfig) -> RemoteFile:
    """Resolve a pasted SharePoint URL via Graph's /shares endpoint.

    Note this fetches ``/driveItem`` (metadata), not ``/driveItem/content``.
    The content endpoint returns bytes only, which would leave the provenance
    banner with nothing to show and no eTag to key the cache on.
    """
    token = _acquire_token(config)
    url = f"{GRAPH_ROOT}/shares/{config.share_token}/driveItem"
    response = _get(url, token)
    if response.status_code != 200:
        raise GraphError(_explain_graph_failure(response, "the shared file URL"))
    return _remote_from_item(_json(response, "file lookup"), config)


def locate_file(config: SharePointConfig) -> RemoteFile:
    """Resolve the configured file to a concrete drive item."""
    if config.addresses_by_url:
        return _locate_by_url(config)

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

    return _remote_from_item(_json(item_response, "file lookup"), config)


def download_file(config: SharePointConfig, remote: RemoteFile) -> bytes:
    """Download the workbook's bytes."""
    token = _acquire_token(config)
    if remote.drive_id and remote.item_id:
        url = f"{GRAPH_ROOT}/drives/{remote.drive_id}/items/{remote.item_id}/content"
    else:  # fall back to shares addressing when the item ids are unavailable
        url = f"{GRAPH_ROOT}/shares/{config.share_token}/driveItem/content"
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
