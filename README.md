# Tri9T AI — CT-200 Ingestion & QA Pipeline

Backend API that ingests the CardioTrack CT-200 Home Blood Pressure Monitor manual
into a versioned, queryable tree and generates QA test cases from user-selected
sections — with traceability that survives document re-versioning.

**Stack:** FastAPI · Pydantic v2 · SQLAlchemy 2 · SQLite · Groq (`openai/gpt-oss-20b`) · PyMuPDF · pytest

**Assignment:** AI Engineering Internship — Tri9T AI

---

## Table of contents

- [Quick start](#quick-start)
- [Environment variables](#environment-variables-env)
- [The v1 → v2 versioning flow](#how-to-trigger-the-v1--v2-re-ingestion-flow)
- [Test suite](#test-suite)
- [Project structure](#project-structure)
- [Troubleshooting](#troubleshooting)
- [Design decisions](#design-decisions)

---
---------------------------------------------------------------------------------------
## Quick start

```bash
# 1. Clone
git clone <your-repo-url> tri9t-ai
cd tri9t-ai

# 2. Create virtualenv
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate

# 3. Install
pip install -r requirements.txt

# 4. Configure
cp .env.example .env
# Edit .env — set GROQ_API_KEY=gsk_...
# Get free key: https://console.groq.com/keys

# 5. Ingest both versions
python -m scripts.ingest_cli data/raw/ct200_manual.pdf    "CardioTrack CT-200"
python -m scripts.ingest_cli data/raw/ct200_manual_v2.pdf "CardioTrack CT-200"

# 6. Run tests
pytest -q
# → all tests pass

# 7. Start API
uvicorn app.main:app --reload --port 8000
---------------------------------------------------------------------------------------
##Environment variables (.env)

Variable	
GROQ_API_KEY
LLM_PROVIDER
LLM_MODEL
LLM_MAX_ATTEMPTS
DATABASE_URL
OCR_ENABLED
GENERATIONS_DIR
DATA_RAW_DIR
---------------------------------------------------------------------------------------
# --- Start clean (optional) ---
Remove-Item tri9t.db -ErrorAction SilentlyContinue
Remove-Item data/generations/*.json -ErrorAction SilentlyContinue

# --- Ingest v1 ---
python -m scripts.ingest_cli data/raw/ct200_manual.pdf "CardioTrack CT-200"
# → ✅ Ingested v1 — 30 nodes

# --- Generate test cases against a v1 node that changes in v2 ---
# Battery Life: v1 says "300 cycles, 15%" → v2 says "250 cycles, 10%"
$bid = (Invoke-RestMethod "http://localhost:8000/search?q=battery%20life&version=1")[0].id
$bsel = Invoke-RestMethod -Method Post -Uri http://localhost:8000/selections `
        -ContentType "application/json" `
        -Body (@{name="battery-v1-qa"; node_ids=@($bid)} | ConvertTo-Json)
$bgen = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/selections/$($bsel.id)/generate"
Write-Host "Generated against v1: $($bgen.status)"

# --- Ingest v2 ---
python -m scripts.ingest_cli data/raw/ct200_manual_v2.pdf "CardioTrack CT-200"
# → ✅ Ingested v2 — 31 nodes

# --- Check staleness (should be STALE / CRITICAL) ---
Invoke-RestMethod "http://localhost:8000/generations/$($bgen.id)/staleness" | ConvertTo-Json -Depth 5


---------------------------------------------------------------------------------------
#Contrast with a fresh section (Overpressure Protection, identical in v1 and v2):

$oid = (Invoke-RestMethod "http://localhost:8000/search?q=overpressure&version=1")[0].id
$osel = Invoke-RestMethod -Method Post -Uri http://localhost:8000/selections `
        -ContentType "application/json" `
        -Body (@{name="overpressure-v1-qa"; node_ids=@($oid)} | ConvertTo-Json)
$ogen = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/selections/$($osel.id)/generate"

Invoke-RestMethod "http://localhost:8000/generations/$($ogen.id)/staleness" | ConvertTo-Json -Depth 5
# → { "overall_status": "fresh", "overall_severity": "none", "reason": "unchanged" }
---------------------------------------------------------------------------------------
#commands that prove the output is real
#Fetch the actual body text behind each hash
python -c "
from app.db import SessionLocal
from app.models import Node

s = SessionLocal()

h1 = '51688c6b664383f8072cb970aff5f693de9a15f8152193ae0716d82b0b0520e2'
h2 = '032a488e546604d0efbf72780f256fc17e6bf61eac925f7dabec28eb1c476c50'

n1 = s.query(Node).filter(Node.content_hash == h1).first()
n2 = s.query(Node).filter(Node.content_hash == h2).first()

print('=== snapshot (v1) ===')
print('node id    :', n1.id if n1 else 'NOT FOUND')
print('version_id :', n1.version_id if n1 else '')
print('heading    :', n1.heading if n1 else '')
print('body       :')
print(repr(n1.body) if n1 else '')

print()
print('=== current (v2) ===')
print('node id    :', n2.id if n2 else 'NOT FOUND')
print('version_id :', n2.version_id if n2 else '')
print('heading    :', n2.heading if n2 else '')
print('body       :')
print(repr(n2.body) if n2 else '')
"
#Recompute the hash from the body text
python -c "
from app.db import SessionLocal
from app.models import Node
from app.ingest.tree_builder import _normalize, _hash

s = SessionLocal()

for h in ['51688c6b664383f8072cb970aff5f693de9a15f8152193ae0716d82b0b0520e2',
          '032a488e546604d0efbf72780f256fc17e6bf61eac925f7dabec28eb1c476c50']:
    n = s.query(Node).filter(Node.content_hash == h).first()
    if not n:
        print(f'{h[:12]}... NOT FOUND in DB'); continue
    recomputed = _hash(_normalize(n.heading.strip().lower()) + '\n' + _normalize(n.body.strip()))
    match = '✅ MATCH' if recomputed == h else '❌ MISMATCH'
    print(f'stored     : {h}')
    print(f'recomputed : {recomputed}')
    print(f'verdict    : {match}')
    print()
"

#Verify via the API 
# Get a v1 Battery Life node ID
$bid_v1 = (Invoke-RestMethod "http://localhost:8000/search?q=battery%20life&version=1")[0].id

# Fetch the v1 node with full body
$v1_node = Invoke-RestMethod "http://localhost:8000/nodes/$bid_v1"
Write-Host "`n=== v1 body ===" -ForegroundColor Cyan
Write-Host $v1_node.body
Write-Host "`nv1 hash: $($v1_node.content_hash)" -ForegroundColor Yellow

# Fetch the same node from v2 (find by heading — same logical_id)
$v2_nodes = Invoke-RestMethod "http://localhost:8000/search?q=battery%20life&version=2"
$v2_node = Invoke-RestMethod "http://localhost:8000/nodes/$($v2_nodes[0].id)"
Write-Host "`n=== v2 body ===" -ForegroundColor Cyan
Write-Host $v2_node.body
Write-Host "`nv2 hash: $($v2_node.content_hash)" -ForegroundColor Yellow

# Same-logical-id confirmation
Write-Host "`n=== logical_id identical? ===" -ForegroundColor Magenta
Write-Host "v1 logical_id: $($v1_node.logical_id)"
Write-Host "v2 logical_id: $($v2_node.logical_id)"
Write-Host "match: $($v1_node.logical_id -eq $v2_node.logical_id)"

# The API-level diff
Write-Host "`n=== /nodes/{id}/diff hunks ===" -ForegroundColor Cyan
Invoke-RestMethod "http://localhost:8000/nodes/$bid_v1/diff" | ConvertTo-Json -Depth 5


---------------------------------------------------------------------------------------
#Quick curl 
# Top-level sections (latest = v2)
Invoke-RestMethod "http://localhost:8000/sections" | ConvertTo-Json -Depth 3

# v1 sections
Invoke-RestMethod "http://localhost:8000/sections?version=1" | ConvertTo-Json -Depth 3

# Search
Invoke-RestMethod "http://localhost:8000/search?q=overpressure" | ConvertTo-Json -Depth 3

# Get a specific node
$node = (Invoke-RestMethod "http://localhost:8000/search?q=overpressure")[0].id
Invoke-RestMethod "http://localhost:8000/nodes/$node" | ConvertTo-Json -Depth 3
---------------------------------------------------------------------------------------
API reference
Full interactive docs: http://localhost:8000/docs

Endpoint	Method	Purpose
/health	GET	Liveness check
/debug/llm-config	GET	Show running provider, model, key prefix
/sections?version=latest|N	GET	Top-level sections
/nodes/{id}	GET	Node detail with body, hash, children
/search?q=...&version=...	GET	Search heading + body
/nodes/{id}/diff	GET	Cross-version diff hunks
/selections	POST	Create version-pinned selection
/selections	GET	List all selections
/selections/{id}	GET	Get with pinned snapshots
/selections/{id}	DELETE	Delete
/selections/{id}/generate?force=false	POST	Generate test cases
/generations?selection_id=X&node_id=Y	GET	List with staleness summary
/generations/{id}	GET	Full record + staleness block
/generations/{id}/staleness	GET	Staleness-only report
---------------------------------------------------------------------------------------
#Test Suite 

pytest -q                          # full suite
pytest -v                          # verbose
pytest tests/test_staleness.py    # one module
pytest -k "survives_reingest"     # one test
pytest -k "critical"              # all critical-severity tests
---------------------------------------------------------------------------------------
#Project Structure
tri9t-ai/
├── app/
│   ├── main.py               FastAPI entry point
│   ├── config.py             Settings (absolute .env path — CWD-safe)
│   ├── db.py                 SQLAlchemy engine + session
│   ├── models.py             Document, Version, Node, Selection, SelectionItem
│   ├── schemas.py            Pydantic request/response models
│   ├── ingest/
│   │   ├── pdf_reader.py     PyMuPDF + optional PaddleOCR fallback
│   │   ├── heading_classifier.py   Regex + style-based detection
│   │   └── tree_builder.py   Stack-based hierarchy reconstruction
│   ├── versioning/
│   │   ├── matcher.py        Path + number-prefix matching
│   │   └── pipeline.py       Re-ingest orchestration
│   ├── api/
│   │   ├── browse.py         /sections, /nodes, /search, /diff
│   │   ├── selections.py     /selections
│   │   ├── generation.py     /selections/{id}/generate
│   │   └── retrieval.py      /generations (+ staleness)
│   ├── llm/
│   │   ├── base.py           LLMClient protocol + factory
│   │   ├── groq.py           Groq via httpx
│   │   ├── gemini.py         Gemini via httpx
│   │   └── fake.py           Deterministic fake (for tests)
│   └── generation/
│       ├── schemas.py        TestCase, GeneratedTestCases (Pydantic)
│       ├── prompts.py        SYSTEM_PROMPT, PROMPT_VERSION
│       ├── service.py        Orchestration: retry + idempotency
│       ├── staleness.py      Severity-aware staleness check
│       └── store.py          JSON file persistence
├── data/
│   ├── raw/                  Input PDFs (v1, v2)
│   └── generations/          LLM output (one JSON per generation)
├── scripts/
│   └── ingest_cli.py         CLI: python -m scripts.ingest_cli <pdf> <doc_name>
├── tests/                    All tests
├── docs/
│   ├── APPROACH.md           Full approach document
│   ├── postman_collection.json
│   └── submission_email.md
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md                 (this file)

---------------------------------------------------------------------------------------

Troubleshooting
Symptom	Fix
401 Unauthorized from LLM	GROQ_API_KEY invalid or revoked. Test directly: curl.exe https://api.groq.com/openai/v1/models -H "Authorization: Bearer gsk_..." → must return HTTP 200. Get fresh key at https://console.groq.com/keys
/debug/llm-config shows groq_key_length: 0	.env not loaded. Verify file exists at repo root, saved as UTF-8 without BOM, and restart uvicorn (.env is not hot-reloaded)
Port 8000 already in use	Get-NetTCPConnection -LocalPort 8000 → Stop-Process -Id <pid> -Force
pytest fails on test_selection_survives_reingest	Ensure both data/raw/ct200_manual.pdf and data/raw/ct200_manual_v2.pdf exist
status: MALFORMED on generation	Check attempts[].error — usually schema mismatch or 401. Retry with ?force=true after fixing key
Staleness shows not_applicable	The generation was MALFORMED (no test cases exist). Regenerate with ?force=true
Staleness shows fresh when you expected stale	You generated against the latest version (v2). Use ?version=1 in /search to pin to v1 for the v1→v2 comparison
path shows â¯ (mojibake)	Old generation created before unicode normalization. Regenerate with ?force=true
ModuleNotFoundError: app	You must be in tri9t-ai/ directory when running pytest/python
sqlalchemy.exc.OperationalError: no such table	DB not created. Run python -m scripts.ingest_cli ... once (creates tables)
---------------------------------------------------------------------------------------
Design decisions

Version-pinned selections store frozen snapshots — not just foreign keys — so old selections resolve to their exact original text after re-ingest. Verified by test_selection_survives_reingest.

Two-tier staleness classifier — a regex pre-filter runs before word-diff, so 300→250 cycles is critical while starts→begins is minor. This is the assignment's core question about whether one-word changes should be treated the same as threshold changes.

Content-addressed idempotency — same prompt content hits the cache; failed (MALFORMED) generations never poison the cache.

5 layers of LLM validation — provider JSON mode → fence stripping → field coercion → schema validation → enum enforcement.

Permanent LLM errors fail fast — 401/403 stop after 1 attempt instead of burning 3.

MALFORMED generations report not_applicable staleness — nothing to be fresh about when there are zero test cases.

Deliberately no UI, no auth, no generic parser — all explicitly out of scope per the assignment.

Deliberate non-features (per assignment "out of scope" section):

❌ No UI — JSON API only. /docs is FastAPI's auto-generated Swagger. Postman collection covers the demo.

❌ No auth — every endpoint is unauthenticated by design.

❌ No generic PDF parser — heuristics are CT-200-specific (TABLE_HEADER_WORDS, NUMBERED regex). Would fail gracefully on other PDFs — which is per the assignment's framing.

❌ No auto-regeneration — staleness is detected automatically but re-generation requires an explicit POST.

---------------------------------------------------------------------------------------
