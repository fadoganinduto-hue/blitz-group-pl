# Getting the dashboard in front of the team

Twenty minutes, no Azure subscription, no IT ticket. This is the whole thing.

The dashboard is a **viewer**. The Group P&L workbook in SharePoint stays the
source of truth for anything anyone needs to act on — that's why this is short.

---

### 1. Push the repo to GitHub — private

```
gh repo create blitz-group-pl --private --source=. --push
```

### 2. Deploy

[share.streamlit.io](https://share.streamlit.io) → sign in with GitHub →
**Create app** → this repo, branch `main`, main file `app.py`.

Give it a URL you'll remember: `blitz-group-pl` →
`https://blitz-group-pl.streamlit.app`

It'll start and show an upload box. Expected — secrets come next.

### 3. One field in Azure

[portal.azure.com](https://portal.azure.com) → **Entra ID → App registrations →
Blitz Group PL → Authentication → Add a platform → Web**

Redirect URI:

```
https://blitz-group-pl.streamlit.app/oauth2callback
```

Tick **ID tokens**, Save. That's the only Azure you touch.

### 4. Paste the secrets

```
python -c "import secrets; print(secrets.token_hex(32))"
```

Then in Streamlit Cloud → your app → **⋮ → Settings → Secrets**:

```toml
AZURE_TENANT_ID = "c13caea6-fef3-4328-bba6-4ff95ae9badc"
AZURE_CLIENT_ID = "0e6e2a05-275a-4367-9847-3f096d1c12ea"
AZURE_CLIENT_SECRET = "the-secret-VALUE"

[workbook]
mode = "sharepoint"

[files]
file_url = "the SharePoint URL of the workbook"

[auth]
redirect_uri = "https://blitz-group-pl.streamlit.app/oauth2callback"
cookie_secret = "the-64-character-string-you-just-generated"
client_id = "0e6e2a05-275a-4367-9847-3f096d1c12ea"
client_secret = "the-secret-VALUE"
server_metadata_url = "https://login.microsoftonline.com/c13caea6-fef3-4328-bba6-4ff95ae9badc/v2.0/.well-known/openid-configuration"
```

Done. Send the link. Everyone signs in with their normal Blitz account —
nothing to remember, nothing to distribute.

---

## The two things that will bite you

**The three `AZURE_*` keys must stay above every `[section]` header.** A bare
TOML key belongs to whatever section came before it, so one below `[workbook]`
becomes `workbook.AZURE_TENANT_ID` and the app says its credentials are
missing. Same trap as last time.

**`server_metadata_url` must carry the tenant GUID, not `common`.** With
`common`, any Microsoft account on earth can sign in — a personal Outlook
address included. Test it with a personal account before you send the link; it
should be refused.

---

## Not needed

- `allowed_domains` in `[auth]` — only if you want to exclude Entra **guest**
  accounts (external auditors, agency staff). Skip it to admit everyone at
  Blitz.
- Hosting it inside Azure. There is a guide for that if Finance ever decides
  the SharePoint credential may not sit outside the tenant; ask for it then.

## Worth ten minutes, later

The credential above grants `Files.Read.All` — read access to every file in the
Blitz tenant, not just this workbook. Narrowing it to `Sites.Selected` on the
Finance site takes one portal change and one admin consent, and it's the
difference between one P&L file and everything the company has ever stored.
Nothing to do with the dashboard; worth doing anyway.
