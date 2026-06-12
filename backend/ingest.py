"""
ingest.py — Document ingestion pipeline for ARIA RAG system.

Reads documents from the data_files/ directory, splits them into chunks,
generates embeddings via sentence-transformers, and stores everything in
a persistent ChromaDB collection.

Optimizations over v1:
  • Tracks file modification times — skips files unchanged since last ingest
  • Uses updated chunk sizes from config (800 chars, 100 overlap)
  • Clearer progress logging

Usage (run from the backend/ directory):
    python -m ingest          # ingest new/changed docs only
    python -m ingest --reset  # wipe DB and re-ingest from scratch
"""

import os
import sys
import json
import shutil
import argparse
import glob

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document

# ── Config import (works whether run as module or standalone) ─────────
try:
    from config import (
        RAG_DATA_DIR,
        RAG_CHROMA_DIR,
        RAG_COLLECTION_NAME,
        RAG_EMBEDDING_MODEL,
        RAG_CHUNK_SIZE,
        RAG_CHUNK_OVERLAP,
    )
except ImportError:
    # Fallback if config hasn't been updated yet
    _PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    RAG_DATA_DIR       = os.path.join(_PROJECT_ROOT, "data_files")
    RAG_CHROMA_DIR     = os.path.join(_PROJECT_ROOT, "chroma_db")
    RAG_COLLECTION_NAME = "aria_docs"
    RAG_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
    RAG_CHUNK_SIZE     = 800
    RAG_CHUNK_OVERLAP  = 100

# ── File-change tracker path ─────────────────────────────────────────
_TRACKER_PATH = os.path.join(RAG_CHROMA_DIR, "_ingest_tracker.json")


def _load_tracker() -> dict[str, float]:
    """Load {filename: mtime} from the tracker file."""
    if os.path.isfile(_TRACKER_PATH):
        try:
            with open(_TRACKER_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_tracker(tracker: dict[str, float]) -> None:
    """Persist the tracker to disk."""
    os.makedirs(os.path.dirname(_TRACKER_PATH), exist_ok=True)
    with open(_TRACKER_PATH, "w", encoding="utf-8") as f:
        json.dump(tracker, f, indent=2)


# ── Supported loaders ────────────────────────────────────────────────
def _load_text(path: str) -> list[Document]:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()
    return [Document(page_content=text, metadata={"source": os.path.basename(path)})]


def _load_pdf(path: str) -> list[Document]:
    try:
        from langchain_community.document_loaders import PyPDFLoader
        return PyPDFLoader(path).load()
    except ImportError:
        print(f"  ⚠  pypdf not installed — skipping {os.path.basename(path)}")
        return []


_LOADERS = {
    ".txt": _load_text,
    ".md":  _load_text,
    ".pdf": _load_pdf,
}


# ── Core pipeline ────────────────────────────────────────────────────
def gather_documents(data_dir: str,
                     tracker: dict[str, float] | None = None,
                     force: bool = False) -> tuple[list[Document], dict[str, float]]:
    """
    Load every supported file from *data_dir* and return raw Documents.

    If *tracker* is provided and *force* is False, skip files whose
    modification time hasn't changed since last ingest.

    Returns (docs, updated_tracker).
    """
    docs: list[Document] = []
    new_tracker: dict[str, float] = dict(tracker) if tracker else {}
    if not os.path.isdir(data_dir):
        print(f"[Ingest] Data directory not found: {data_dir}")
        return docs, new_tracker

    for ext, loader_fn in _LOADERS.items():
        for filepath in glob.glob(os.path.join(data_dir, f"*{ext}")):
            basename = os.path.basename(filepath)
            mtime = os.path.getmtime(filepath)

            # Skip unchanged files (unless force/reset)
            if not force and tracker and basename in tracker:
                if tracker[basename] == mtime:
                    print(f"  ⏭  Skipping {basename} (unchanged)")
                    continue

            print(f"  📄 Loading {basename}")
            loaded = loader_fn(filepath)
            docs.extend(loaded)
            new_tracker[basename] = mtime

    return docs, new_tracker


def split_documents(docs: list[Document],
                    chunk_size: int = RAG_CHUNK_SIZE,
                    chunk_overlap: int = RAG_CHUNK_OVERLAP) -> list[Document]:
    """Split documents into smaller overlapping chunks."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        add_start_index=True,
    )
    return splitter.split_documents(docs)


def build_vectorstore(chunks: list[Document],
                      chroma_dir: str = RAG_CHROMA_DIR,
                      collection: str = RAG_COLLECTION_NAME,
                      model_name: str = RAG_EMBEDDING_MODEL) -> Chroma:
    """Embed chunks and persist them into ChromaDB."""
    print(f"[Ingest] Loading embedding model: {model_name}")
    embeddings = HuggingFaceEmbeddings(model_name=model_name)

    print(f"[Ingest] Storing {len(chunks)} chunks in ChromaDB → {chroma_dir}")
    vectorstore = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        collection_name=collection,
        persist_directory=chroma_dir,
        # Use COSINE distance to match our normalized MiniLM embeddings. Without
        # this Chroma defaults to squared-L2, and langchain's relevance score
        # (1 - distance) then maps even good matches below RAG_MIN_RELEVANCE,
        # so retrieval silently returns nothing (Issue 1).
        collection_metadata={"hnsw:space": "cosine"},
    )

    return vectorstore


def run_ingest(reset: bool = False) -> None:
    """Full pipeline: load → split → embed → store."""
    print("\n" + "=" * 55)
    print("  ARIA RAG — Document Ingestion Pipeline")
    print("=" * 55)

    if reset and os.path.isdir(RAG_CHROMA_DIR):
        print(f"[Ingest] Resetting — deleting {RAG_CHROMA_DIR}")
        shutil.rmtree(RAG_CHROMA_DIR)

    # Load tracker (empty after reset since dir was deleted)
    tracker = _load_tracker() if not reset else {}

    # 1. Gather (skip unchanged files unless reset)
    docs, updated_tracker = gather_documents(
        RAG_DATA_DIR, tracker=tracker, force=reset
    )
    if not docs:
        if tracker:
            print("[Ingest] All files up-to-date — nothing to ingest")
        else:
            print("[Ingest] No documents found. Place .txt / .md / .pdf files in:")
            print(f"         {RAG_DATA_DIR}")
        return

    print(f"[Ingest] Loaded {len(docs)} document(s)")

    # 2. Split
    chunks = split_documents(docs)
    print(f"[Ingest] Split into {len(chunks)} chunk(s)  "
          f"(size={RAG_CHUNK_SIZE}, overlap={RAG_CHUNK_OVERLAP})")

    # 3. Embed & store
    vs = build_vectorstore(chunks)
    count = vs._collection.count()

    # 4. Save tracker
    _save_tracker(updated_tracker)

    print(f"\n✅ Ingestion complete — {count} vectors stored in ChromaDB")
    print(f"   Collection : {RAG_COLLECTION_NAME}")
    print(f"   Location   : {RAG_CHROMA_DIR}")
    print(f"   Chunk size : {RAG_CHUNK_SIZE} chars, {RAG_CHUNK_OVERLAP} overlap\n")


# ── CLI entry point ──────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest documents into ARIA RAG vector store")
    parser.add_argument("--reset", action="store_true",
                        help="Delete existing vector DB and re-ingest from scratch")
    args = parser.parse_args()
    run_ingest(reset=args.reset)
