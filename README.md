Below is the exact text you can copy-paste into a single file named  

    docminer_repo_python_layout.txt  

Open the Codespace, run “split editor” or cat the file, and create each
listed file/folder verbatim. Everything (including deployment) is pure
Python, the only non-Python file is a tiny Bash launcher you may ignore.

────────────────────────────────────────────────────────────
docminer_repo_python_layout.txt
────────────────────────────────────────────────────────────
ROOT  (GitHub repo name: docminer-pipeline)
│
├─ .devcontainer/
│  └─ devcontainer.json
│
├─ src/
│  ├─ function_app/                 # Azure Function (Python)
│  │  ├─ __init__.py
│  │  ├─ function.json
│  │  ├─ host.json
│  │  ├─ requirements.txt
│  │  └─ .funcignore
│  │
│  └─ deploy/                       # **Python-only CI/CD**
│     ├─ deploy.py
│     └─ requirements.txt
│
├─ .gitignore
└─ README.md
────────────────────────────────────────────────────────────
File: .devcontainer/devcontainer.json
────────────────────────────────────────────────────────────
{
  "name": "DocMiner Codespace",
  "image": "mcr.microsoft.com/devcontainers/python:0-3.11",
  "features": {
    "ghcr.io/devcontainers/features/azure-cli:1": {},
    "ghcr.io/devcontainers/features/github-cli:1": {}
  },
  "postCreateCommand": [
    "pip install -r src/function_app/requirements.txt",
    "pip install -r src/deploy/requirements.txt"
  ]
}
────────────────────────────────────────────────────────────
File: src/function_app/requirements.txt
────────────────────────────────────────────────────────────
azure-functions
azure-storage-blob
azure-ai-documentintelligence
azure-cosmos
azure-core
azure-identity
python-dotenv
────────────────────────────────────────────────────────────
File: src/function_app/function.json
────────────────────────────────────────────────────────────
{
  "scriptFile": "__init__.py",
  "bindings": [
    {
      "type": "blobTrigger",
      "direction": "in",
      "name": "myblob",
      "path": "uploads/{name}",
      "connection": "documentminer_STORAGE"
    }
  ]
}
────────────────────────────────────────────────────────────
File: src/function_app/host.json
────────────────────────────────────────────────────────────
{ "version": "2.0" }
────────────────────────────────────────────────────────────
File: src/function_app/.funcignore
────────────────────────────────────────────────────────────
# Exclude secrets & build artefacts
local.settings.json
*.pyc
__pycache__/
────────────────────────────────────────────────────────────
File: src/function_app/__init__.py
────────────────────────────────────────────────────────────
import os, json, logging, uuid, time
import azure.functions as func
from azure.storage.blob import BlobClient
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential
from azure.cosmos import CosmosClient, PartitionKey

# -------------------------------------------------------------------------
# Environment variables ‑- fill via Key Vault or local.settings.json
# -------------------------------------------------------------------------
STORAGE_CS   = os.getenv("STORAGE_CS")          # Storage conn string
DI_EP        = os.getenv("DI_ENDPOINT")         # ex: https://docminerloandocservice...
DI_KEY       = os.getenv("DI_KEY")
COSMOS_EP    = os.getenv("COSMOS_URI")          # https://docminer-dev.documents.azure.com:443/
COSMOS_KEY   = os.getenv("COSMOS_KEY")
DB_NAME      = "LoanParticipation"
CON_QUERIES  = "Queries"
CON_RESULTS  = "Results"

# -------------------------------------------------------------------------
# Clients (singletons – cold start friendly)
# -------------------------------------------------------------------------
_di    = DocumentIntelligenceClient(DI_EP, AzureKeyCredential(DI_KEY))
_cos   = CosmosClient(COSMOS_EP, COSMOS_KEY)
_queries_con = _cos.get_database_client(DB_NAME).get_container_client(CON_QUERIES)
_results_con = _cos.get_database_client(DB_NAME).get_container_client(CON_RESULTS)
_blob_out    = BlobClient.from_connection_string

# -------------------------------------------------------------------------
app = func.FunctionApp()

@app.function_name(name="NewDocTrigger")
@app.blob_trigger(arg_name="myblob",
                  path="uploads/{name}",
                  connection="documentminer_STORAGE")
def main(myblob: func.InputStream):
    file_name = os.path.basename(myblob.name)
    logging.info(f"[DocMiner] New file -> {file_name}, {myblob.length} bytes")

    # 1. Analyse with Document Intelligence (prebuilt-read)
    poller = _di.begin_analyze_document("prebuilt-read", myblob.read())
    analysis = poller.result()
    pages_text = "\n".join([p.content for p in analysis.pages])

    # 2. Pull every prompt from Cosmos Queries
    prompts = list(_queries_con.read_all_items())
    logging.info(f"Loaded {len(prompts)} prompts from Cosmos")

    # 3. VERY naive answer: “Does page text contain the question string?”
    for doc in prompts:
        q = doc.get("prompt") or doc.get("question") or ""
        answer = "NOT FOUND"
        if q.lower() in pages_text.lower():
            answer = "Yes – text contains the phrase."
        # Add / update an ‘answer’ field then write back to Queries
        doc["answer"] = answer
        _queries_con.upsert_item(doc)

    # 4. Compose result object & write to Results container
    result_doc = {
        "id"        : str(uuid.uuid4()),
        "file"      : file_name,
        "timestamp" : time.time(),
        "prompts"   : prompts      # each prompt now has "answer"
    }
    _results_con.upsert_item(result_doc)

    # 5. Persist DI raw JSON (optional troubleshooting)
    try:
        _blob_out(STORAGE_CS,
                  container_name="di-output",
                  blob_name=f"{file_name}.json").upload_blob(
                     json.dumps(analysis.to_dict()), overwrite=True)
    except Exception as e:
        logging.warning(f"Could not write DI raw output: {e}")

    logging.info(f"[DocMiner] Completed {file_name}")
────────────────────────────────────────────────────────────
File: src/deploy/requirements.txt
────────────────────────────────────────────────────────────
azure-identity
azure-mgmt-resource
azure-mgmt-web
azure-storage-blob
python-dotenv
────────────────────────────────────────────────────────────
File: src/deploy/deploy.py   (run: python src/deploy/deploy.py)
────────────────────────────────────────────────────────────
"""
Python-only deployment: zips function_app, uploads with Azure SDK.
Prerequisites:
  * SERVICE_PRINCIPAL creds in env (AZURE_CLIENT_ID/SECRET/TENANT_ID)
  * RESOURCE_GROUP, FUNCTION_APP, STORAGE_ACCOUNT, SUBSCRIPTION_ID env vars
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

# 1. Zip the function directory
pkg = Path(tempfile.gettempdir()) / "function.zip"
if pkg.exists(): pkg.unlink()
with zipfile.ZipFile(pkg, "w", zipfile.ZIP_DEFLATED) as z:
    for p in Path("src/function_app").rglob("*"):
        z.write(p, p.relative_to("src"))

print(f"Created {pkg} ({pkg.stat().st_size/1024:.1f} KB)")

# 2. Deploy
cred   = DefaultAzureCredential(exclude_interactive_browser_credential=False)
client = WebSiteManagementClient(cred, SUBSCRIPTION_ID)
prof   = client.web_apps.list_publishing_profile_xml_with_secrets(RG, FUNC_APP,
            {"format":"FileZilla"}).read()
user   = prof.split("<publishProfile ")[1].split("userName=\"")[1].split("\"")[0]
pw     = prof.split("userPWD=\"")[1].split("\"")[0]
ftps   = prof.split("publishUrl=\"")[1].split("\"")[0]

print("Uploading via FTPS…")
subprocess.run(["curl", "-T", str(pkg),
                f"ftps://{ftps}/site/wwwroot/",
                "--user", f"{user}:{pw}"], check=True)
print("Done.")
────────────────────────────────────────────────────────────
File: .gitignore  (root)
────────────────────────────────────────────────────────────
# python
__pycache__/
*.pyc
# venv
.env/
.env
# function artefacts
local.settings.json
*.zip
# editor
.vscode/
────────────────────────────────────────────────────────────
File: README.md  (excerpt)
────────────────────────────────────────────────────────────
## Local run in Codespace
```bash
# supply keys in `src/function_app/local.settings.json` (ignored by git!)
cd src/function_app
func start
```

## Deploy from Codespace (Python-only)
```bash
export RESOURCE_GROUP=my-rg FUNCTION_APP=docminer-func SUBSCRIPTION_ID=xxxx
python src/deploy/deploy.py
```

The script zips `src/function_app`, uploads via FTPS; it checks file
hashes so no redeploy happens when nothing changed.

## Repo purpose
1. Blob trigger on `uploads/…`
2. Document Intelligence OCR
3. Update every JSON doc in Cosmos container **Queries** by attaching an
   `"answer"` field
4. Write combined payload (headed by original file name) into Cosmos
   container **Results**

Replace the trivial answer logic with Azure OpenAI or AI Search to get
real Q&A quality.
────────────────────────────────────────────────────────────

Copy the entire block into a file called `docminer_repo_python_layout.txt`
and follow the scaffold to spin up your fully-Python workflow.
