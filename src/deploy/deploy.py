"""
Python-only deployment: zips function_app, uploads with Azure SDK.

Prerequisites
-------------
• SERVICE_PRINCIPAL creds in env (AZURE_CLIENT_ID / SECRET / TENANT_ID)
• RESOURCE_GROUP, FUNCTION_APP, STORAGE_ACCOUNT, SUBSCRIPTION_ID env vars
"""

import os, shutil, tempfile, subprocess, sys, zipfile
from pathlib import Path
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.mgmt.web import WebSiteManagementClient

load_dotenv()                       # picks up .env or Codespace secrets
RG              = os.getenv("RESOURCE_GROUP")
FUNC_APP        = os.getenv("FUNCTION_APP")
SUBSCRIPTION_ID = os.getenv("SUBSCRIPTION_ID")

if not all([RG, FUNC_APP, SUBSCRIPTION_ID]):
    sys.exit("Missing env vars. See README.md")

# 1. Zip the function directory ------------------------------------------------
pkg = Path(tempfile.gettempdir()) / "function.zip"
if pkg.exists():
    pkg.unlink()

with zipfile.ZipFile(pkg, "w", zipfile.ZIP_DEFLATED) as z:
    for p in Path("src/function_app").rglob("*"):
        z.write(p, p.relative_to("src"))

print(f"Created {pkg} ({pkg.stat().st_size/1024:.1f} KB)")

# 2. Deploy --------------------------------------------------------------------
cred   = DefaultAzureCredential(exclude_interactive_browser_credential=False)
client = WebSiteManagementClient(cred, SUBSCRIPTION_ID)

# Azure SDK 2023+ returns StreamDownloadGenerator (iterator, no .read()).
# Older SDKs returned an object that *did* expose .read().
def download_publishing_profile(rg: str, app: str) -> str:
    resp = client.web_apps.list_publishing_profile_xml_with_secrets(
        rg, app, {"format": "FileZilla"}
    )

    # Newer versions have .readall()
    if hasattr(resp, "readall"):
        data = resp.readall()
    else:
        # StreamDownloadGenerator – concatenate the chunks
        data = b"".join(chunk for chunk in resp)

    return data.decode("utf-8")     # convert bytes → str for string parsing

prof_xml = download_publishing_profile(RG, FUNC_APP)

user = prof_xml.split("<publishProfile ")[1].split("userName=\"")[1].split("\"")[0]
pw   = prof_xml.split("userPWD=\"")[1].split("\"")[0]
ftps = prof_xml.split("publishUrl=\"")[1].split("\"")[0]

print("Uploading via FTPS…")
subprocess.run(
    ["curl", "-T", str(pkg),
     f"ftps://{ftps}/site/wwwroot/",
     "--user", f"{user}:{pw}"],
    check=True
)

print("Done.")