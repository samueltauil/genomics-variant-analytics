metadata description = 'Installs the private governed query service onto the existing in-VNet verification VM for OpenSpec task 8.7.'

param location string
param verificationVmName string
param lakeStorageAccountName string
param lakeFilesystem string
param pipelineClientId string
param tags object

@description('Port exposed only on the verification VM private interface.')
param servicePort int = 8080

@description('Blob path under the healthcare filesystem that holds the synthetic governed-query CSV.')
param datasetRelativePath string = 'SampleData/Genomics/private-query/task-8-7/synthetic-governed-variants.csv'

resource verificationVm 'Microsoft.Compute/virtualMachines@2024-11-01' existing = {
  name: verificationVmName
}

var installScriptTemplate = '''
set -euo pipefail

install_root="/home/genomicsops/private-query-live"
mkdir -p "$install_root"
chown genomicsops:genomicsops "$install_root"

cat > "$install_root/governed_query_service.py" <<'PY'
import csv
import json
import sqlite3
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import os

PORT = int(os.environ["GOVERNED_QUERY_PORT"])
PIPELINE_CLIENT_ID = os.environ["PIPELINE_CLIENT_ID"]
LAKE_ACCOUNT = os.environ["LAKE_ACCOUNT"]
LAKE_FILESYSTEM = os.environ["LAKE_FILESYSTEM"]
DATASET_RELATIVE_PATH = os.environ["DATASET_RELATIVE_PATH"]
STORAGE_SUFFIX = os.environ["STORAGE_SUFFIX"]
WORKDIR = Path(os.environ["GOVERNED_QUERY_WORKDIR"])
DB_PATH = WORKDIR / "governed-query.sqlite3"

DEIDENTIFIED_COLUMNS = [
    "CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO",
    "sample_id", "cohort_id", "gene", "transcript", "variant_consequence",
    "genotype", "allele_frequency", "reference_build", "pipeline_version",
    "source_file_uri", "ingestion_timestamp",
]
ALL_COLUMNS = DEIDENTIFIED_COLUMNS[:9] + ["research_subject_id"] + DEIDENTIFIED_COLUMNS[9:]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def imds_token() -> str:
    request = urllib.request.Request(
        "http://169.254.169.254/metadata/identity/oauth2/token"
        "?api-version=2018-02-01"
        "&resource=https%3A%2F%2Fstorage.azure.com%2F"
        f"&client_id={urllib.parse.quote(PIPELINE_CLIENT_ID)}",
        headers={"Metadata": "true"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))["access_token"]


def download_dataset() -> bytes:
    token = imds_token()
    url = (
        f"https://{LAKE_ACCOUNT}.blob.{STORAGE_SUFFIX}/"
        f"{LAKE_FILESYSTEM}/{DATASET_RELATIVE_PATH}"
    )
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "x-ms-version": "2023-11-03",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def initialize_store() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS variant_records (
            CHROM TEXT,
            POS INTEGER,
            ID TEXT,
            REF TEXT,
            ALT TEXT,
            QUAL REAL,
            FILTER TEXT,
            INFO TEXT,
            sample_id TEXT,
            research_subject_id TEXT,
            cohort_id TEXT,
            gene TEXT,
            transcript TEXT,
            variant_consequence TEXT,
            genotype TEXT,
            allele_frequency REAL,
            reference_build TEXT,
            pipeline_version TEXT,
            source_file_uri TEXT,
            ingestion_timestamp TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            occurred_at TEXT NOT NULL,
            principal TEXT NOT NULL,
            operation TEXT NOT NULL,
            gene TEXT,
            requested_subject_linkage INTEGER NOT NULL,
            row_count INTEGER NOT NULL,
            outcome TEXT NOT NULL,
            detail TEXT NOT NULL
        )
        """
    )
    return connection


def refresh_records(connection: sqlite3.Connection) -> None:
    payload = download_dataset().decode("utf-8")
    reader = csv.DictReader(payload.splitlines())
    rows = list(reader)
    with connection:
        connection.execute("DELETE FROM variant_records")
        connection.executemany(
            """
            INSERT INTO variant_records (
                CHROM, POS, ID, REF, ALT, QUAL, FILTER, INFO, sample_id,
                research_subject_id, cohort_id, gene, transcript, variant_consequence,
                genotype, allele_frequency, reference_build, pipeline_version,
                source_file_uri, ingestion_timestamp
            )
            VALUES (
                :CHROM, :POS, :ID, :REF, :ALT, :QUAL, :FILTER, :INFO, :sample_id,
                :research_subject_id, :cohort_id, :gene, :transcript, :variant_consequence,
                :genotype, :allele_frequency, :reference_build, :pipeline_version,
                :source_file_uri, :ingestion_timestamp
            )
            """,
            rows,
        )


def audit(connection: sqlite3.Connection, principal: str, operation: str, gene: str | None,
          requested_subject_linkage: bool, row_count: int, outcome: str, detail: str) -> None:
    with connection:
        connection.execute(
            """
            INSERT INTO audit_log
                (occurred_at, principal, operation, gene, requested_subject_linkage, row_count, outcome, detail)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (utc_now(), principal, operation, gene, 1 if requested_subject_linkage else 0,
             row_count, outcome, detail),
        )


CONNECTION = initialize_store()


class Handler(BaseHTTPRequestHandler):
    def _json(self, status: int, payload: dict) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if parsed.path == "/health":
            self._json(200, {"status": "ok", "captured_at_utc": utc_now()})
            return

        if parsed.path == "/audit":
            limit = min(int(params.get("limit", ["10"])[0]), 25)
            rows = [
                dict(row)
                for row in CONNECTION.execute(
                    """
                    SELECT occurred_at, principal, operation, gene, requested_subject_linkage,
                           row_count, outcome, detail
                    FROM audit_log
                    ORDER BY audit_id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            ]
            self._json(200, {"rows": rows})
            return

        if parsed.path != "/query":
            self._json(404, {"error": "not_found"})
            return

        principal = params.get("principal", ["deidentified-analyst"])[0]
        gene = params.get("gene", [""])[0].strip()
        include_subject_linkage = params.get("include_subject_linkage", ["false"])[0].lower() == "true"
        if not gene:
            audit(CONNECTION, principal, "query", None, include_subject_linkage, 0, "denied", "gene required")
            self._json(400, {"error": "gene is required"})
            return

        refresh_records(CONNECTION)

        if include_subject_linkage:
            detail = "subject linkage is not available on the de-identified governed query interface"
            audit(CONNECTION, principal, "query", gene, True, 0, "denied", detail)
            self._json(403, {"error": detail})
            return

        sql = """
            SELECT CHROM, POS, ID, REF, ALT, QUAL, FILTER, INFO, sample_id, cohort_id,
                   gene, transcript, variant_consequence, genotype, allele_frequency,
                   reference_build, pipeline_version, source_file_uri, ingestion_timestamp
            FROM variant_records
            WHERE gene = ?
            ORDER BY cohort_id, sample_id, POS
        """
        rows = [dict(row) for row in CONNECTION.execute(sql, (gene,)).fetchall()]
        audit(CONNECTION, principal, "query", gene, False, len(rows), "success", "de-identified result set returned")
        self._json(200, {"query": sql.strip(), "row_count": len(rows), "rows": rows})

    def log_message(self, format: str, *args) -> None:
        return


HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
PY

chown genomicsops:genomicsops "$install_root/governed_query_service.py"

cat > /etc/systemd/system/governed-query.service <<'UNIT'
[Unit]
Description=Private governed query service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=genomicsops
Group=genomicsops
WorkingDirectory=/home/genomicsops/private-query-live
Environment="GOVERNED_QUERY_PORT=__SERVICE_PORT__"
Environment="PIPELINE_CLIENT_ID=__PIPELINE_CLIENT_ID__"
Environment="LAKE_ACCOUNT=__LAKE_ACCOUNT__"
Environment="LAKE_FILESYSTEM=__LAKE_FILESYSTEM__"
Environment="DATASET_RELATIVE_PATH=__DATASET_RELATIVE_PATH__"
Environment="STORAGE_SUFFIX=__STORAGE_SUFFIX__"
Environment="GOVERNED_QUERY_WORKDIR=/home/genomicsops/private-query-live"
ExecStart=/usr/bin/python3 /home/genomicsops/private-query-live/governed_query_service.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable governed-query.service >/dev/null
systemctl restart governed-query.service
systemctl is-active governed-query.service
'''

var installScript = replace(replace(replace(replace(replace(replace(replace(
  installScriptTemplate,
  '__SERVICE_PORT__',
  string(servicePort)),
  '__PIPELINE_CLIENT_ID__',
  pipelineClientId),
  '__LAKE_ACCOUNT__',
  lakeStorageAccountName),
  '__LAKE_FILESYSTEM__',
  lakeFilesystem),
  '__DATASET_RELATIVE_PATH__',
  datasetRelativePath),
  '__STORAGE_SUFFIX__',
  az.environment().suffixes.storage),
  '\r',
  '')

resource installGovernedQuery 'Microsoft.Compute/virtualMachines/runCommands@2024-11-01' = {
  name: 'install-governed-query-service'
  parent: verificationVm
  location: location
  tags: tags
  properties: {
    asyncExecution: false
    timeoutInSeconds: 3600
    treatFailureAsDeploymentFailure: true
    source: {
      script: installScript
    }
  }
}

output runCommandId string = installGovernedQuery.id
