# Tri9T AI — CT-200 Ingestion & QA Pipeline

## Setup
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Ingest v1
Place `ct200_manual_v1.pdf` in `data/raw/`, then:
```bash
python scripts/ingest_cli.py data/raw/ct200_manual_v1.pdf "CardioTrack CT-200"
```

## Run tests
```bash
pytest -q
```

## Roadmap
- [x] Module 1: scaffold + ingestion + tests
- [ ] Module 2: versioning + v1↔v2 matching
- [ ] Module 3: browse API
- [ ] Module 4: selections (version-pinned)
- [ ] Module 5: LLM generation (validated + retry)
- [ ] Module 6: staleness + retrieval API