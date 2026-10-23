"""python scripts/ingest_cli.py data/raw/ct200_manual_v1.pdf "CardioTrack CT-200" """
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import Base, engine, SessionLocal
from app.ingest.pipeline import ingest_pdf

def main():
    if len(sys.argv) < 2:
        print("usage: python scripts/ingest_cli.py <pdf_path> [document_name]")
        sys.exit(1)
    path = sys.argv[1]
    name = sys.argv[2] if len(sys.argv) > 2 else "CardioTrack CT-200"
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        v, n = ingest_pdf(db, path, name)
        print(f"✅ Ingested v{v.version_number} — {n} nodes — version_id={v.id}")
    finally:
        db.close()

if __name__ == "__main__":
    main()