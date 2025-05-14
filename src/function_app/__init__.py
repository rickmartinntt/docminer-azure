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
