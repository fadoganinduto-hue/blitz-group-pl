"""Tests for the SharePoint diagnostic script's token-claim decoding."""
from __future__ import annotations

import base64
import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "check_sharepoint_access",
    Path(__file__).resolve().parent.parent / "scripts" / "check_sharepoint_access.py",
)
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)


def _fake_jwt(claims: dict) -> str:
    def seg(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
    return f"{seg({'alg': 'RS256'})}.{seg(claims)}.signature"


def test_decodes_roles_from_a_real_shaped_token():
    """The `roles` claim is the authoritative list of granted app permissions."""
    token = _fake_jwt({
        "aud": "https://graph.microsoft.com",
        "app_displayname": "Blitz Ops Dashboard — SharePoint Reader",
        "roles": ["Files.Read.All"],
        "tid": "abc",
    })
    claims = check._decode_claims(token)
    assert claims["roles"] == ["Files.Read.All"]
    assert claims["app_displayname"].startswith("Blitz Ops Dashboard")


@pytest.mark.parametrize("padding_len", [0, 1, 2, 3])
def test_decodes_regardless_of_base64_padding(padding_len):
    """JWT segments strip '=' padding; the decoder must restore it."""
    claims = {"roles": ["Sites.Selected"], "pad": "x" * padding_len}
    assert check._decode_claims(_fake_jwt(claims))["roles"] == ["Sites.Selected"]


@pytest.mark.parametrize("bad", ["", "not-a-jwt", "a.b", "a.!!!.c"])
def test_malformed_tokens_return_empty_rather_than_crashing(bad):
    assert check._decode_claims(bad) == {}


def test_no_roles_claim_is_distinguishable_from_empty_roles():
    """A token with no roles means consent was never granted — must not look OK."""
    assert check._decode_claims(_fake_jwt({"aud": "x"})).get("roles") is None


def test_permission_table_flags_write_scopes():
    """Write scopes must be described as such so they get challenged."""
    for name, desc in check.READ_PERMISSIONS.items():
        if "ReadWrite" in name or "FullControl" in name:
            assert "WRITE" in desc or "full control" in desc, name
    assert "Sites.Selected" in check.READ_PERMISSIONS
    assert "allow-listed" in check.READ_PERMISSIONS["Sites.Selected"]
