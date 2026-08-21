"""
Index PDFs using local PageIndex with OpenRouter, and output project-compatible JSON files.

Usage:
    python index_with_openrouter.py
"""
import sys
import os
import json
import uuid
import time
from pathlib import Path
from datetime import datetime

# Fix Windows terminal encoding for Unicode output
sys.stdout.reconfigure(encoding="utf-8")

# Add local PageIndex Github clone to path
PAGEINDEX_PATH = r"d:\Python\PageIndex_Github\PageIndex"
sys.path.insert(0, PAGEINDEX_PATH)

from dotenv import load_dotenv
load_dotenv(override=True)

# Import local PageIndex
try:
    from pageindex.page_index import page_index
    import PyPDF2
except ImportError as e:
    raise ImportError(
        f"Failed to import local pageindex or PyPDF2. Ensure PageIndex is cloned at {PAGEINDEX_PATH} and requirements are installed. Error: {e}"
    )

# Directories
BASE_DIR = Path(__file__).parent
PDFS_DIR = BASE_DIR / "PDFS"
LOCAL_DATA_DIR = BASE_DIR / "pageindex_data"
DOC_IDS_PATH = BASE_DIR / "doc_ids.json"

# OpenRouter Configuration
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")
if not OPENROUTER_KEY:
    raise ValueError("Missing OPENROUTER_API_KEY in .env file!")

# Set the key for litellm
os.environ["OPENROUTER_API_KEY"] = OPENROUTER_KEY

# Model choice (GPT-4o is top-tier and works perfectly with the OpenRouter account)
MODEL = "openrouter/openai/gpt-4o"


def map_structure_node(node):
    """Recursively map local structure node schema to cloud schema expected by tools.py."""
    new_node = {
        "title": node.get("title", ""),
        "node_id": node.get("node_id", ""),
        "page_index": node.get("start_index", node.get("physical_index", 1)),
    }
    if "summary" in node:
        new_node["summary"] = node["summary"]
    if "text" in node:
        new_node["text"] = node["text"]
    if "nodes" in node and isinstance(node["nodes"], list):
        new_node["nodes"] = [map_structure_node(child) for child in node["nodes"]]
    return new_node


def main():
    print("=" * 60)
    print("  PageIndex Local + OpenRouter Indexer")
    print(f"  Model: {MODEL}")
    print("=" * 60)

    fresh = "--fresh" in sys.argv
    print(f"  Fresh indexing: {fresh}")
    print("=" * 60)

    # Ensure output directory exists
    LOCAL_DATA_DIR.mkdir(exist_ok=True)

    # Load existing doc_ids
    doc_ids = {}
    if DOC_IDS_PATH.exists():
        try:
            with open(DOC_IDS_PATH, "r", encoding="utf-8") as f:
                doc_ids = json.load(f)
        except Exception as e:
            print(f"[WARN] Failed to load existing doc_ids.json: {e}")

    # Find PDFs to process
    pdf_files = sorted(PDFS_DIR.glob("*.pdf"))
    if not pdf_files:
        print(f"\n[ERROR] No PDFs found in {PDFS_DIR}!")
        return

    print(f"\n[DIR] Found {len(pdf_files)} PDFs in {PDFS_DIR}:")
    for pdf in pdf_files:
        print(f"   - {pdf.name}")

    to_index = []
    for pdf in pdf_files:
        local_file = LOCAL_DATA_DIR / f"{pdf.stem}.json"
        if local_file.exists() and not fresh:
            print(f"   - {pdf.name} is already indexed (local JSON exists).")
        else:
            to_index.append(pdf)

    if not to_index:
        print("\n[OK] All PDFs are already indexed. Nothing to do!")
        return

    print(f"\n[INFO] Need to index {len(to_index)} PDFs.")

    for idx, pdf in enumerate(to_index, 1):
        name = pdf.stem
        print(f"\n[{idx}/{len(to_index)}] Indexing: {pdf.name}...")
        
        # 1. Run local pageindex logic using OpenRouter
        try:
            print("   Running PageIndex tree extraction (this may take 1-2 minutes)...")
            result = page_index(
                doc=str(pdf),
                model=MODEL,
                if_add_node_summary="yes",
                if_add_node_text="yes",
                if_add_node_id="yes",
                if_add_doc_description="yes",
            )
            print("   [OK] PageIndex structure extracted.")
        except Exception as e:
            print(f"   [FAIL] PageIndex extraction failed: {e}")
            continue

        # 2. Extract raw page content for OCR compatibility
        print("   Extracting page texts...")
        pages = []
        try:
            with open(pdf, "rb") as f:
                pdf_reader = PyPDF2.PdfReader(f)
                for i, page in enumerate(pdf_reader.pages, 1):
                    pages.append({"page": i, "content": page.extract_text() or ""})
        except Exception as e:
            print(f"   [FAIL] Failed to extract PDF text: {e}")
            continue

        # 3. Format into the cloud JSON schema
        doc_id = doc_ids.get(pdf.name)
        if not doc_id:
            doc_id = f"pi-local-{uuid.uuid4().hex[:16]}"
            doc_ids[pdf.name] = doc_id

        cloud_data = {
            "metadata": {
                "id": doc_id,
                "name": pdf.name,
                "description": result.get("doc_description", ""),
                "status": "completed",
                "createdAt": datetime.now().isoformat(),
                "pageNum": len(pages),
                "folderId": None,
            },
            "tree": {
                "doc_id": doc_id,
                "status": "completed",
                "retrieval_ready": True,
                "result": [map_structure_node(node) for node in result.get("structure", [])],
                "metadata": {},
            },
            "pages": {
                "doc_id": doc_id,
                "status": "completed",
                "retrieval_ready": True,
                "result": [
                    {
                        "images": [],
                        "markdown": p["content"],
                        "page_index": p["page"],
                        "extended_node_candidates": [],
                    }
                    for p in pages
                ],
                "metadata": {},
            },
        }

        # 4. Save file
        save_path = LOCAL_DATA_DIR / f"{name}.json"
        try:
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(cloud_data, f, indent=2, ensure_ascii=False)
            print(f"   [OK] Saved to: {save_path}")
        except Exception as e:
            print(f"   [FAIL] Failed to save JSON file: {e}")
            continue

        # 5. Save updated doc_ids.json
        try:
            with open(DOC_IDS_PATH, "w", encoding="utf-8") as f:
                json.dump(doc_ids, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"   [WARN] Failed to update doc_ids.json: {e}")

        # Sleep briefly between files
        if idx < len(to_index):
            print("   Waiting 5 seconds before next document...")
            time.sleep(5)

    print("\n" + "=" * 60)
    print("[OK] Indexing completed!")
    print(f"     Output folder: {LOCAL_DATA_DIR}")
    print(f"     Updated mappings: {DOC_IDS_PATH}")
    print("=" * 60)


if __name__ == "__main__":
    main()
