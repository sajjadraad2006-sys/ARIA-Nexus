"""
rag_engine.py — RAG query engine for ARIA.

Loads the persistent ChromaDB vector store and exposes a simple query
interface used by server.py to retrieve document context at chat time.

Optimizations over v1:
  • LRU cache with TTL — skip embedding + search for repeated questions
  • Relevance-score filtering — discard low-quality chunks (< threshold)
  • Context size cap — prevent blowing the LLM context window
  • Numbered chunks for LLM referenceability

Usage from server.py:
    from rag_engine import RAGEngine
    rag = RAGEngine()
    context = rag.query("What is the delivery policy?")
    # (Documents are ingested with the flat `ingest.py` module.)
"""

import os
import time
import warnings

# ── Force CPU-only for this process ───────────────────────────────────
# The Flask/RAG process must NOT touch the GPU so llama-server gets all VRAM.
# This must happen BEFORE torch or any CUDA-aware library is imported.
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
os.environ.setdefault("CUDA_DEVICE_ORDER", "PCI_BUS_ID")

# Suppress noisy startup warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", message=".*CUDA.*")

from langchain_huggingface import HuggingFaceEmbeddings
try:
    from langchain_chroma import Chroma          # langchain-chroma package (new)
except ImportError:
    from langchain_community.vectorstores import Chroma  # fallback

# ── Config import ─────────────────────────────────────────────────────
try:
    from config import (
        RAG_CHROMA_DIR,
        RAG_COLLECTION_NAME,
        RAG_EMBEDDING_MODEL,
        RAG_TOP_K,
        RAG_MIN_RELEVANCE,
        RAG_CACHE_TTL,
        RAG_MAX_CONTEXT_CHARS,
    )
except ImportError:
    _PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    RAG_CHROMA_DIR        = os.path.join(_PROJECT_ROOT, "chroma_db")
    RAG_COLLECTION_NAME   = "aria_docs"
    RAG_EMBEDDING_MODEL   = "sentence-transformers/all-MiniLM-L6-v2"
    RAG_TOP_K             = 4
    RAG_MIN_RELEVANCE     = 0.3
    RAG_CACHE_TTL         = 300
    RAG_MAX_CONTEXT_CHARS = 3000


def _safe_vector_count(vectorstore) -> int:
    """Return the number of vectors in a Chroma store.

    Prefers the stable public ``.get()`` API, falls back to the (efficient but
    version-sensitive) private collection counter, and finally to 0. Wrapped so
    a Chroma version bump that moves/renames internals can never crash startup.
    """
    if vectorstore is None:
        return 0
    # Preferred: stable public API (ids are always returned).
    try:
        data = vectorstore.get(include=[])
        ids = data.get("ids") if isinstance(data, dict) else None
        if ids is not None:
            return len(ids)
    except Exception:
        pass
    # Fallback: underlying collection counter (private, version-sensitive).
    try:
        return vectorstore._collection.count()
    except Exception:
        return 0


class RAGEngine:
    """Thin wrapper around ChromaDB for document retrieval with caching."""

    def __init__(self,
                 chroma_dir: str = RAG_CHROMA_DIR,
                 collection_name: str = RAG_COLLECTION_NAME,
                 model_name: str = RAG_EMBEDDING_MODEL,
                 top_k: int = RAG_TOP_K):
        self._chroma_dir = chroma_dir
        self._collection_name = collection_name
        self._top_k = top_k
        self._vectorstore = None
        self._available = False

        # ── Query cache: {query_text: (timestamp, result_string)} ──
        self._cache: dict[str, tuple[float, str]] = {}
        self._cache_ttl = RAG_CACHE_TTL

        if not os.path.isdir(chroma_dir):
            print(f"[RAG] Vector DB not found at {chroma_dir} — "
                  f"run 'python -m ingest' first")
            return

        try:
            print(f"[RAG] Loading embedding model: {model_name}")
            embeddings = HuggingFaceEmbeddings(
                model_name=model_name,
                model_kwargs={"device": "cpu"},
                encode_kwargs={"normalize_embeddings": True},
                show_progress=False,         # hide tqdm loading bar
            )

            self._vectorstore = Chroma(
                collection_name=collection_name,
                embedding_function=embeddings,
                persist_directory=chroma_dir,
                # COSINE to match normalized embeddings (see ingest.py / Issue 1).
                collection_metadata={"hnsw:space": "cosine"},
            )

            count = _safe_vector_count(self._vectorstore)
            if count > 0:
                self._available = True
                print(f"[RAG] ✅ Ready — {count} vectors in collection "
                      f"'{collection_name}'")
            else:
                print(f"[RAG] Collection '{collection_name}' is empty — "
                      f"run ingest first")
        except Exception as exc:
            print(f"[RAG] Failed to load vector store: {exc}")

    # ── Public API ────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """True if the vector store is loaded and contains documents."""
        return self._available

    def query(self, text: str, k: int | None = None) -> str:
        """
        Retrieve the top-k most relevant document chunks for *text*.

        Returns a single string with numbered, relevance-filtered chunks,
        or an empty string if nothing relevant is found.

        Features over v1:
          • Cache hit → instant return (no embedding/search)
          • Relevance threshold → filters out noisy chunks
          • Context cap → prevents blowing the LLM context window
        """
        if not self._available or self._vectorstore is None:
            return ""

        # ── Cache check ───────────────────────────────────────
        cache_key = text.strip().lower()
        cached = self._cache.get(cache_key)
        if cached:
            ts, result = cached
            if (time.time() - ts) < self._cache_ttl:
                print(f"[RAG] Cache HIT for: {text[:50]!r}")
                return result
            else:
                del self._cache[cache_key]   # expired

        k = k or self._top_k
        try:
            # ── Relevance-scored search ───────────────────────
            results = self._vectorstore.similarity_search_with_relevance_scores(
                text, k=k
            )
            if not results:
                self._cache[cache_key] = (time.time(), "")
                return ""

            # ── Filter by relevance threshold ─────────────────
            filtered = [
                (doc, score) for doc, score in results
                if score >= RAG_MIN_RELEVANCE
            ]
            if not filtered:
                print(f"[RAG] All {len(results)} chunks below relevance "
                      f"threshold ({RAG_MIN_RELEVANCE})")
                self._cache[cache_key] = (time.time(), "")
                return ""

            # ── Build numbered context with size cap ──────────
            chunks: list[str] = []
            total_chars = 0
            for i, (doc, score) in enumerate(filtered, 1):
                source = doc.metadata.get("source", "unknown")
                chunk_text = (
                    f"[{i}] (Source: {source}, relevance: {score:.2f})\n"
                    f"{doc.page_content}"
                )
                if total_chars + len(chunk_text) > RAG_MAX_CONTEXT_CHARS:
                    print(f"[RAG] Context cap reached at chunk {i} "
                          f"({total_chars} chars)")
                    break
                chunks.append(chunk_text)
                total_chars += len(chunk_text)

            context = "\n\n".join(chunks)
            print(f"[RAG] Retrieved {len(chunks)}/{len(results)} chunk(s) "
                  f"({total_chars} chars) for: {text[:60]!r}")

            # ── Store in cache ────────────────────────────────
            self._cache[cache_key] = (time.time(), context)
            return context

        except Exception as exc:
            print(f"[RAG] Query error: {exc}")
            return ""

    def clear_cache(self) -> None:
        """Flush the query cache (e.g. after re-ingestion)."""
        self._cache.clear()
        print("[RAG] Cache cleared")


# ── Quick standalone test ─────────────────────────────────────────────
if __name__ == "__main__":
    engine = RAGEngine()
    if engine.is_available():
        test_query = "delivery policy"
        print(f"\n--- Test query: '{test_query}' ---")
        result = engine.query(test_query)
        if result:
            print(result)
        else:
            print("No results found.")
        # Test cache
        print("\n--- Same query again (should be cache hit) ---")
        result2 = engine.query(test_query)
        print("Cache working!" if result2 == result else "Cache miss")
    else:
        print("RAG engine is not available. Run ingest first.")


# ══════════════════════════════════════════════════════════════════════
#  SpatialMemoryEngine — Visual Landmark Memory for Autonomous Navigation
# ══════════════════════════════════════════════════════════════════════

try:
    from config import (
        RAG_CHROMA_DIR,
        RAG_EMBEDDING_MODEL,
        SPATIAL_MEMORY_COLLECTION,
        SPATIAL_MEMORY_MAX_ENTRIES,
        SPATIAL_MEMORY_TOP_K,
    )
except ImportError:
    SPATIAL_MEMORY_COLLECTION = "aria_spatial_memory"
    SPATIAL_MEMORY_MAX_ENTRIES = 200
    SPATIAL_MEMORY_TOP_K = 5


class SpatialMemoryEngine:
    """Stores and retrieves spatial observations for autonomous navigation.

    Unlike RAGEngine which handles static documents, SpatialMemoryEngine
    builds a living map of the robot's environment through camera
    observations.  Each memory contains:

      * **Document**: Natural language scene description from the Vision LLM
      * **Metadata**: timestamp, mission context, primary/secondary landmarks

    The engine uses a separate ChromaDB collection so it never conflicts
    with the document RAG system.  All methods are thread-safe for use
    from background navigation threads.
    """

    def __init__(self,
                 chroma_dir: str = RAG_CHROMA_DIR,
                 collection_name: str = SPATIAL_MEMORY_COLLECTION,
                 model_name: str = RAG_EMBEDDING_MODEL,
                 max_entries: int = SPATIAL_MEMORY_MAX_ENTRIES,
                 top_k: int = SPATIAL_MEMORY_TOP_K):
        self._chroma_dir = chroma_dir
        self._collection_name = collection_name
        self._max_entries = max_entries
        self._top_k = top_k
        self._vectorstore = None
        self._available = False
        self._embeddings = None
        self._memory_count = 0

        try:
            print(f"[SpatialMem] Loading embedding model: {model_name}")
            self._embeddings = HuggingFaceEmbeddings(
                model_name=model_name,
                model_kwargs={"device": "cpu"},
                encode_kwargs={"normalize_embeddings": True},
                show_progress=False,         # hide tqdm loading bar
            )

            self._vectorstore = Chroma(
                collection_name=collection_name,
                embedding_function=self._embeddings,
                persist_directory=chroma_dir,
            )

            self._memory_count = self._vectorstore._collection.count()
            self._available = True
            print(f"[SpatialMem] ✅ Ready — {self._memory_count} memories in "
                  f"'{collection_name}'")
        except Exception as exc:
            print(f"[SpatialMem] Failed to load: {exc}")

    # ── Public API ────────────────────────────────────────────────

    def is_available(self) -> bool:
        return self._available

    def count(self) -> int:
        if self._vectorstore:
            n = _safe_vector_count(self._vectorstore)
            if n:
                return n
        return self._memory_count

    def remember(self, observation: str, metadata: dict | None = None) -> bool:
        """Store a new spatial observation.

        Called from a background thread to avoid blocking the nav loop.

        Parameters
        ----------
        observation : str
            Natural language scene description from the Vision LLM.
        metadata : dict
            Keys: timestamp, mission, primary_landmark, secondary_landmarks
        """
        if not self._available or not self._vectorstore:
            return False

        try:
            meta = dict(metadata) if metadata else {}
            meta.setdefault("timestamp", int(time.time()))
            meta.setdefault("mission", "explore")
            meta.setdefault("primary_landmark", "")
            meta.setdefault("secondary_landmarks", "")

            # Generate a unique ID
            doc_id = f"mem_{meta['timestamp']}_{self._memory_count}"

            from langchain_core.documents import Document
            doc = Document(page_content=observation, metadata=meta)

            self._vectorstore.add_documents([doc], ids=[doc_id])
            self._memory_count += 1

            # Evict oldest if over limit
            if self._memory_count > self._max_entries:
                self._evict_oldest()

            print(f"[SpatialMem] 💾 Stored: {observation[:60]}…")
            return True
        except Exception as exc:
            print(f"[SpatialMem] Store error: {exc}")
            return False

    def recall(self, query: str, k: int | None = None) -> list[dict]:
        """Retrieve relevant spatial memories for a query.

        Returns a list of dicts: {text, timestamp, mission, primary_landmark, ...}
        """
        if not self._available or not self._vectorstore:
            return []

        k = k or self._top_k
        try:
            results = self._vectorstore.similarity_search_with_relevance_scores(
                query, k=k
            )
            memories = []
            for doc, score in results:
                if score < 0.2:
                    continue
                memories.append({
                    "text": doc.page_content,
                    "score": round(score, 3),
                    **doc.metadata,
                })
            print(f"[SpatialMem] 🔍 Recalled {len(memories)} memories for: "
                  f"{query[:50]!r}")
            return memories
        except Exception as exc:
            print(f"[SpatialMem] Recall error: {exc}")
            return []

    def recall_as_context(self, query: str, k: int | None = None) -> str:
        """Retrieve memories formatted as an LLM context block."""
        memories = self.recall(query, k)
        if not memories:
            return ""
        lines = []
        for i, m in enumerate(memories, 1):
            ts = m.get("timestamp", 0)
            ago = int(time.time() - ts) if ts else 0
            mins = ago // 60
            landmark = m.get("primary_landmark", "")
            lines.append(
                f"[Memory {i}] ({mins}m ago, landmark: {landmark}) "
                f"{m['text']}"
            )
        return "\n".join(lines)

    def get_all_memories(self, limit: int = 50) -> list[dict]:
        """Return all stored memories for the UI timeline."""
        if not self._available or not self._vectorstore:
            return []
        try:
            collection = self._vectorstore._collection
            results = collection.get(
                limit=limit,
                include=["documents", "metadatas"],
            )
            memories = []
            docs = results.get("documents", [])
            metas = results.get("metadatas", [])
            for doc, meta in zip(docs, metas):
                memories.append({"text": doc, **(meta or {})})
            # Sort by timestamp descending (newest first)
            memories.sort(key=lambda m: m.get("timestamp", 0), reverse=True)
            return memories[:limit]
        except Exception as exc:
            print(f"[SpatialMem] get_all error: {exc}")
            return []

    def clear_memory(self) -> bool:
        """Wipe all spatial memories."""
        if not self._available:
            return False
        try:
            # Delete and recreate the collection
            import chromadb
            client = chromadb.PersistentClient(path=self._chroma_dir)
            client.delete_collection(self._collection_name)
            self._vectorstore = Chroma(
                collection_name=self._collection_name,
                embedding_function=self._embeddings,
                persist_directory=self._chroma_dir,
            )
            self._memory_count = 0
            print("[SpatialMem] 🧹 All memories cleared")
            return True
        except Exception as exc:
            print(f"[SpatialMem] Clear error: {exc}")
            return False

    def _evict_oldest(self) -> None:
        """Remove the oldest memories to stay under max_entries."""
        try:
            collection = self._vectorstore._collection
            results = collection.get(
                include=["metadatas"],
            )
            ids = results.get("ids", [])
            metas = results.get("metadatas", [])
            if len(ids) <= self._max_entries:
                return
            # Sort by timestamp and remove oldest
            paired = list(zip(ids, metas))
            paired.sort(key=lambda p: p[1].get("timestamp", 0))
            to_remove = len(paired) - self._max_entries
            remove_ids = [p[0] for p in paired[:to_remove]]
            collection.delete(ids=remove_ids)
            self._memory_count = _safe_vector_count(self._vectorstore)
            print(f"[SpatialMem] Evicted {to_remove} oldest memories")
        except Exception as exc:
            print(f"[SpatialMem] Eviction error: {exc}")

