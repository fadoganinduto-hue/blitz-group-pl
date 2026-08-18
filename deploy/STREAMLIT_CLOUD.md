# Hosting on Streamlit Community Cloud, with real Blitz sign-in

The lighter option. No Azure subscription, no IT ticket, no `az` CLI — but
**not** a shared password. Streamlit has built-in OpenID Connect since 1.42, so
you can point it at Microsoft Entra and get the same "sign in with your Blitz
account" experience, in about twenty minutes.

The one thing this option cannot give you is control over where the SharePoint
credential lives — see "What you're accepting" at the bottom, and make that
call deliberately rather than by default.

---

## What you need

- The repo on GitHub (private is fine, and better)
- Permission to add a redirect URI to the existing **Blitz Group PL** app
  registration — a much smaller ask than creating a new one
- No Azure subscription

---

## Step 1 — Deploy the app

1. [share.streamlit.io](https://share.streamlit.io) → sign in with GitHub
2. **Create app** → pick the repo, branch `main`, main file `app.py`
3. Set the URL to something stable, e.g. `blitz-group-pl` →
   `https://blitz-group-pl.streamlit.app`
4. Deploy

It will start, find no credentials, and show the upload box. That's expected —
secrets come next.

---

## Step 2 — Add the redirect URI in Azure

[portal.azure.com](https://portal.azure.com) → **Entra ID → App registrations →
Blitz Group PL → Authentication**

- **Add a platform → Web**
- Redirect URI: `https://blitz-group-pl.streamlit.app/oauth2callback`
- Tick **ID tokens**
- Save

The `/oauth2callback` suffix is required and easy to leave off. Without it
sign-in fails with a redirect-mismatch error that names no cause.

Add `http://localhost:8501/oauth2callback` as a second URI while you're there,
so sign-in works locally too.

---

## Step 3 — Generate a cookie secret

```
python -c "import secrets; print(secrets.token_hex(32))"
```

Copy the output. It signs the session cookie; it is not a password and nobody
needs to remember it.

---

## Step 4 — Fill in the secrets

In Streamlit Cloud: your app → **⋮ → Settings → Secrets**. Paste this, filling
in the three values:

```toml
AZURE_TENANT_ID = "c13caea6-fef3-4328-bba6-4ff95ae9badc"
AZURE_CLIENT_ID = "0e6e2a05-275a-4367-9847-3f096d1c12ea"
AZURE_CLIENT_SECRET = "the-secret-VALUE"

[workbook]
mode = "sharepoint"

[files]
file_url = "https://blitzelectricmobility.sharepoint.com/:x:/s/.../Group_PL.xlsx"

[auth]
redirect_uri = "https://blitz-group-pl.streamlit.app/oauth2callback"
cookie_secret = "the-64-character-string-from-step-3"
client_id = "0e6e2a05-275a-4367-9847-3f096d1c12ea"
client_secret = "the-secret-VALUE"
server_metadata_url = "https://login.microsoftonline.com/c13caea6-fef3-4328-bba6-4ff95ae9badc/v2.0/.well-known/openid-configuration"
allowed_domains = ["rideblitz.com"]
```

Two things that are easy to get wrong and produce confusing failures:

**The three bare `AZURE_*` keys must stay at the TOP, above every `[section]`
header.** In TOML a bare key belongs to whatever section precedes it, so moving
them below `[workbook]` silently turns them into `workbook.AZURE_TENANT_ID` and
the app reports its credentials missing. This is the same trap as before.

**`server_metadata_url` must contain your tenant ID, not `common`.** With
`common`, any Microsoft account on earth can sign in — a personal Outlook
address included. The tenant GUID is what makes this a Blitz-only door.

`allowed_domains` is a second boundary, for Entra **guest** accounts. Guests are
members of your tenant and pass the tenant check; external auditors and agency
staff are usually guests. Leave the list out to admit the whole tenant.

---

## Step 5 — Check it

Open the URL in a private window. You should get "Sign in with Microsoft", then
the dashboard, with your name and a **Sign out** button at the bottom of the
sidebar.

Test the boundary properly: try a personal Microsoft account. It should be
refused. If it gets in, `server_metadata_url` still says `common`.

---

## What you're accepting

Be deliberate about this rather than discovering it later.

**The credential lives on infrastructure you don't run.** The client secret in
those app settings currently grants `Files.Read.All` — read access to *every*
file in the Blitz tenant, every SharePoint site, every OneDrive. Streamlit
Community Cloud is operated by Snowflake and describes real controls (TLS 1.2+,
AES-256 at rest, VPC isolation, penetration testing) under an explicitly shared
responsibility model. The question is not whether their security is competent;
it is whether Finance is content for a tenant-wide read credential to sit
outside your own tenant.

**This is worth fixing regardless of where you host.** Narrowing the permission
to `Sites.Selected` on the Finance site alone shrinks that from "everything the
company has ever stored" to "one workbook". Do it before this goes to the team,
and the hosting question gets a lot less consequential.

**App-level sharing still applies.** If you also use Community Cloud's own
viewer invitations, note that its documentation states invited viewers can
invite further viewers and gain analytics access to your apps. With `[auth]`
configured you don't need that mechanism — leave the app public in Streamlit's
settings and let Entra be the only door.

**No Always On.** Community Cloud sleeps inactive apps; the first visitor after
a quiet spell waits through a wake-up and a fresh workbook fetch.
