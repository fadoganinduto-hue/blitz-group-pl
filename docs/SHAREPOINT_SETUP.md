# Connecting the dashboard to SharePoint

The dashboard can read the Group P&L workbook from one of three places. Pick a
mode in `.streamlit/secrets.toml`; everything else is automatic.

| Mode | Setup effort | Works when hosted? | Use it for |
|---|---|---|---|
| `local` | 5 minutes, no IT | No — needs the sync client | Getting live today, on your Mac |
| `sharepoint` | Azure app registration | **Yes** | The eventual shared deployment |
| `upload` | none | Yes | What-if analysis, and the fallback |

Both live modes show a green **LIVE** strip across the top of the dashboard with
the file name, who last saved it, and when. If that strip is amber and says
MANUAL, you are looking at a file somebody chose by hand — treat the numbers
accordingly.

---

## Your workbook

Confirmed by searching the tenant:

```
Site       /sites/Finance
Library    Shared Documents
Folder     Group PL
File       Group_PL_2026_Upload.xlsx
Host       61nngljuq69wkvzlaiog9kkphca.sharepoint.com
```

**One thing worth raising separately:** there is a second copy of the Group P&L
at `/sites/BlitzInterns/Shared Documents/Group_PL_2026_Upload - Copy VZ.xlsx`,
last modified 4 Aug 2026. Group-level P&L on an interns site is a permissions
question for whoever owns that site, not a technical one — but it's the kind of
thing that's easier to fix now than after someone leaves.

---

## Option A — OneDrive sync (working today, no IT)

You already sync SharePoint folders, so this is the short path.

1. In a browser, open the **Finance** site → **Documents** → the **Group PL** folder.
2. Click **Sync** in the toolbar. OneDrive adds it under something like:
   `~/Library/CloudStorage/OneDrive-SharedLibraries-<Org>/Finance - Documents/Group PL/`
3. Find the exact path — in Terminal:

   ```bash
   ls ~/Library/CloudStorage/*/Finance*/Group\ PL/
   ```

4. Put it in `.streamlit/secrets.toml`:

   ```toml
   [workbook]
   mode = "local"
   path = "/Users/dufadoganinduto/Library/CloudStorage/OneDrive-SharedLibraries-Blitz/Finance - Documents/Group PL/Group_PL_2026_Upload.xlsx"
   ```

5. Restart: `streamlit run app.py`

When Finance saves the workbook, OneDrive syncs it down and **Refresh from
source** picks it up. No export, no upload.

> **Make sure the file is downloaded, not just listed.** OneDrive's Files On-Demand
> shows a cloud icon for files it hasn't fetched. Right-click the Group PL folder →
> **Always Keep on This Device**. Otherwise the app sees a placeholder.

---

## Option B — Microsoft Graph (for the hosted version)

This is what you'll need once the dashboard runs on a server, where there's no
OneDrive client and nobody signed in. The app authenticates as itself.

### First: you may already have this

The Blitz 3PL dashboard already reads SharePoint through an Azure AD app
registration. If that app was granted `Files.Read.All` (tenant-wide read), it
already covers the Finance site — **no new Azure work is needed.** Take the same
three values from that app's Streamlit secrets:

```toml
[workbook]
mode = "sharepoint"

AZURE_TENANT_ID     = "<same as the 3PL dashboard>"
AZURE_CLIENT_ID     = "<same as the 3PL dashboard>"
AZURE_CLIENT_SECRET = "<same as the 3PL dashboard>"

[files]
GROUP_PL = "https://61nngljuq69wkvzlaiog9kkphca.sharepoint.com/sites/Finance/Shared Documents/Group PL/Group_PL_2026_Upload.xlsx"
```

Paste the URL straight from the browser address bar or the file's **⋯ → Copy
link** menu — both work. That is the whole setup.

If that app was scoped with `Sites.Selected` rather than `Files.Read.All`, it
needs the Finance site added to its allow-list before it can read this workbook.
Everything below is only for the case where you are registering a new app.

### What to ask IT for

Send this — it's specific enough to action without a back-and-forth:

> Please create an Azure AD app registration for a read-only internal finance dashboard.
>
> - **Name:** Blitz Group P&L Dashboard
> - **Account type:** Single tenant
> - **Redirect URI:** none (it's a daemon app, client-credentials flow)
> - **API permission:** Microsoft Graph → **Application** permission → `Sites.Selected`
>   *(preferred — least privilege. If `Sites.Selected` isn't workable, `Sites.Read.All` is the fallback.)*
> - **Admin consent:** required, please grant it
> - If using `Sites.Selected`, also grant this app **read** access to the
>   `/sites/Finance` site specifically.
> - **Client secret:** please create one and send me the **Value** (not the Secret ID),
>   along with the **Directory (tenant) ID** and **Application (client) ID**.
>
> The app only reads one workbook. It never writes.

`Sites.Selected` is worth pushing for: `Sites.Read.All` grants read access to
*every* SharePoint site in the tenant, which is a lot of blast radius for one P&L file.

### Doing it yourself, if you have the access

1. **portal.azure.com** → Microsoft Entra ID → **App registrations** → **New registration**
2. Name it, choose **Single tenant**, leave Redirect URI empty → **Register**
3. From the Overview page, copy the **Application (client) ID** and **Directory (tenant) ID**
4. **API permissions** → Add a permission → Microsoft Graph → **Application permissions**
   → search `Sites.Selected` (or `Sites.Read.All`) → Add
5. Click **Grant admin consent** — *the permission does nothing until this is done*
6. **Certificates & secrets** → New client secret → set an expiry → **copy the Value now**.
   Azure shows it exactly once. The Secret ID is not the secret.
7. If you used `Sites.Selected`, an admin also has to grant the app read on the
   Finance site (a small Graph call — IT will know it, or ask and I'll write it out).

### Then configure

Either form works. The URL form matches the 3PL dashboard:

```toml
[workbook]
mode = "sharepoint"

AZURE_TENANT_ID     = "<Directory (tenant) ID>"
AZURE_CLIENT_ID     = "<Application (client) ID>"
AZURE_CLIENT_SECRET = "<the secret VALUE>"

[files]
GROUP_PL = "https://61nngljuq69wkvzlaiog9kkphca.sharepoint.com/sites/Finance/Shared Documents/Group PL/Group_PL_2026_Upload.xlsx"
```

Or address the file explicitly, which does not depend on a share link staying valid:

```toml
[sharepoint]
tenant_id     = "<Directory (tenant) ID>"
client_id     = "<Application (client) ID>"
client_secret = "<the secret VALUE>"
hostname      = "61nngljuq69wkvzlaiog9kkphca.sharepoint.com"
site_path     = "/sites/Finance"
file_path     = "Shared Documents/Group PL/Group_PL_2026_Upload.xlsx"
```

`.streamlit/secrets.toml` is gitignored. Never commit it. When hosting, put
these in the platform's secret store rather than a file.

---

## If something goes wrong

The app translates the common Azure failures into plain English, so read the
error on screen first. The usual ones:

| What you see | What it means |
|---|---|
| "Invalid client secret… the Secret ID is not the value" | You copied the Secret ID. Go back and copy the **Value** column — or the secret expired. |
| "ADMIN CONSENT has not been clicked" | Step 5. Also check the permission was added under **Application**, not Delegated. |
| "Not found… file_path is relative to the site" | Check `site_path` and `file_path` against the SharePoint URL. `file_path` starts with `Shared Documents/`. |
| "Tenant not found" | `tenant_id` is wrong, or is from a different app registration than `client_id`. |
| "No workbook at /Users/…" (local mode) | Path typo, or OneDrive hasn't downloaded the file — see the Files On-Demand note above. |
| "kept changing while being read" | Someone is saving the workbook right now. Click Refresh again. |

To test the connection without launching the whole app:

```python
python3 -c "
import streamlit as st
from streamlit_app.data.graph_client import SharePointConfig, check_connection
print(check_connection(SharePointConfig.from_mapping(st.secrets['sharepoint'])))
"
```

---

## Two deliberate differences from the 3PL dashboard's method

Worth knowing if you are comparing the two implementations side by side.

**1. Metadata is fetched before content.** The 3PL method calls
`/shares/{token}/driveItem/content`, which returns the file's bytes and nothing
else. This dashboard calls `/shares/{token}/driveItem` first to get the eTag,
the last-modified time and who saved it — then downloads. That extra call is
what makes the provenance banner possible.

**2. The cache is keyed on the eTag, not a 5-minute TTL.** The 3PL doc lists
*"data shown is stale even after Excel is edited — cache still valid (5 min
TTL)"* as an expected pitfall, and its status line reports the last successful
**fetch**, not the file's own modified time. On a cache hit that shows a recent
timestamp over potentially older figures. For a dashboard reporting EBITDA to
the board, that combination is the failure mode to design out, so here the cache
key moves the instant the file is saved and the banner reports when the
**workbook** was last written, by whom.

Neither difference changes the Azure setup. The same credentials drive both.

## How refreshing actually works

Worth knowing, because it determines whether you can trust what's on screen.

The app keys its cache on the file's **eTag** (SharePoint) or **mtime+size**
(synced folder) — a value that changes the moment the file is saved and at no
other time. So:

- Nothing is cached on a timer. There's no window where you're shown an old P&L
  because a TTL hasn't lapsed.
- Clicking filters and tabs doesn't re-download anything.
- **Refresh from source** re-reads and rebuilds every view.

Metadata and file contents are always fetched in a single resolution, and the
eTag is re-checked after the download. If someone saves the workbook mid-read,
the app retries rather than showing you a banner for one version and figures
from another. That specific failure — a header claiming a file it isn't
showing — would be worse than no header at all.
