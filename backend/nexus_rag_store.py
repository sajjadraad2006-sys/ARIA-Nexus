# =====================================================================
#  nexus_rag_store.py  --  Real knowledge-base store for ARIA Nexus.
#  Uses the SAME Chroma vector store + embedding model as rag_system,
#  with a graceful in-memory fallback if langchain/chroma are missing.
#  Also provides the chatbot system prompt + RAG context injection.
# =====================================================================
import os
import time
import threading

_lock = threading.RLock()

# Resolve project root relative to THIS file so paths work regardless of
# which directory the Flask server was launched from.
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)


def _cfg():
    d = {
        "data_dir": os.path.join(_PROJECT_ROOT, "data_files"),
        "chroma_dir": os.path.join(_PROJECT_ROOT, "chroma_db"),
        "collection": "aria_docs",
        "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
        "chunk_size": 512,
        "chunk_overlap": 64,
        "top_k": 5,
        "min_relevance": 0.25,
    }
    try:
        import config as c
        d["data_dir"] = getattr(c, "RAG_DATA_DIR", d["data_dir"])
        d["chroma_dir"] = getattr(c, "RAG_CHROMA_DIR", d["chroma_dir"])
        d["collection"] = getattr(c, "RAG_COLLECTION_NAME", d["collection"])
        d["embedding_model"] = getattr(c, "RAG_EMBEDDING_MODEL", d["embedding_model"])
        d["chunk_size"] = int(getattr(c, "RAG_CHUNK_SIZE", d["chunk_size"]))
        d["chunk_overlap"] = int(getattr(c, "RAG_CHUNK_OVERLAP", d["chunk_overlap"]))
        d["top_k"] = int(getattr(c, "RAG_TOP_K", d["top_k"]))
        d["min_relevance"] = float(getattr(c, "RAG_MIN_RELEVANCE", d["min_relevance"]))
    except Exception:
        pass
    return d


SETTINGS = {k: _cfg()[k] for k in ("chunk_size", "chunk_overlap", "top_k", "min_relevance")}


def system_prompt():
    """Personality used by the Nexus chatbot."""
    try:
        import config as c
        p = getattr(c, "RECEPTIONIST_PROMPT", None) or getattr(c, "ROBOT_SYSTEM_PROMPT", None)
        if p:
            return p
    except Exception:
        pass
    return (
        "You are ARIA, an advanced AI assistant for a Smart Home & Robotics Hub. "
        "You ALWAYS respond in English by default. "
        "Only switch to Arabic if the user writes to you in Arabic — and even then, keep technical terms in English. "
        "Be helpful, friendly, and concise (1-3 sentences). "
        "Use the provided knowledge-base context when relevant; if you do not know, say so honestly."
    )


# ---- shared vector store (lazy) -------------------------------------
_VS = {"vs": None, "emb": None, "ok": None}
_engine_ref = {"engine": None}


def set_engine(engine):
    """Share the already-loaded RAGEngine so we don't load MiniLM twice."""
    _engine_ref["engine"] = engine


def _vectorstore(force_reload=False):
    # Fast path: shared RAGEngine already has a live vectorstore — use it
    # directly without touching HuggingFaceEmbeddings at all.
    eng = _engine_ref["engine"]
    if eng is not None and getattr(eng, "_vectorstore", None) is not None:
        return eng._vectorstore

    # Second fast path: we already loaded it in this process — reuse.
    # This is the KEY guard: if _VS["ok"] is True, the vectorstore is cached
    # and we NEVER re-initialize HuggingFaceEmbeddings. Previously, if
    # _engine_ref["engine"] was None (nexus_assistant imports RAGS before
    # server calls set_engine), this fell through and re-loaded the
    # 100-MB embedding model on EVERY assistant command.
    if not force_reload and _VS["ok"] is True and _VS["vs"] is not None:
        return _VS["vs"]

    # Skip permanently if chroma_db doesn't exist yet.
    cfg = _cfg()
    chroma_dir = cfg["chroma_dir"]
    if _VS["ok"] is False and not os.path.isdir(chroma_dir):
        return None
    if not os.path.isdir(chroma_dir):
        return None
    try:
        print("[RAG] Loading embedding model (first time only)...")
        try:
            from langchain_huggingface import HuggingFaceEmbeddings
        except Exception:
            from langchain_community.embeddings import HuggingFaceEmbeddings
        try:
            from langchain_chroma import Chroma
        except Exception:
            from langchain_community.vectorstores import Chroma
        emb = HuggingFaceEmbeddings(
            model_name=cfg["embedding_model"],
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
        vs = Chroma(
            collection_name=cfg["collection"],
            embedding_function=emb,
            persist_directory=chroma_dir,
            collection_metadata={"hnsw:space": "cosine"},
        )
        _VS["vs"] = vs
        _VS["emb"] = emb
        _VS["ok"] = True
        n = 0
        try:
            n = vs._collection.count()
        except Exception:
            pass
        print(f"[RAG] \u2705 Ready \u2014 {n} vectors in collection '{cfg['collection']}'")
        return vs
    except Exception as exc:
        print(f"[RAG-Store] vectorstore load error: {exc}")
        _VS["ok"] = False
        return None


_MEM = {}  # name -> {"text":..., "modified":...}


def _data_path(name):
    cfg = _cfg()
    try:
        os.makedirs(cfg["data_dir"], exist_ok=True)
    except Exception:
        pass
    return os.path.join(cfg["data_dir"], name)


def _splitter():
    cfg = _cfg()
    _cs = int(SETTINGS.get("chunk_size") or cfg["chunk_size"])
    _co = int(SETTINGS.get("chunk_overlap") or cfg["chunk_overlap"])
    # Try multiple import paths — different langchain versions use different modules
    try:
        from langchain.text_splitter import RecursiveCharacterTextSplitter
    except ImportError:
        try:
            from langchain_text_splitters import RecursiveCharacterTextSplitter
        except ImportError:
            from langchain_core.documents import Document  # noqa: F401 — just to verify langchain_core
            # Minimal inline splitter if no langchain text splitter is installed
            class RecursiveCharacterTextSplitter:
                def __init__(self, chunk_size=512, chunk_overlap=64, **kwargs):
                    self._cs = chunk_size
                    self._co = chunk_overlap
                def split_text(self, text):
                    parts = []
                    i = 0
                    while i < len(text):
                        parts.append(text[i:i + self._cs])
                        i += self._cs - self._co
                    return parts or [text]
    return RecursiveCharacterTextSplitter(
        chunk_size=_cs,
        chunk_overlap=_co,
        add_start_index=True,
    )


def _delete_vectors(vs, name):
    try:
        col = getattr(vs, "_collection", None)
        if col is not None:
            col.delete(where={"source": name})
    except Exception:
        pass


def add(title, text):
    name = (title or "").strip()
    if not name:
        name = "note-" + str(int(time.time())) + ".txt"
    if not os.path.splitext(name)[1]:
        name = name + ".txt"
    with _lock:
        try:
            p = _data_path(name)
            with open(p, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"[RAG-Store] Saved file: {p}")
        except Exception as exc:
            print(f"[RAG-Store] WARNING: could not write data file: {exc}")
        vs = _vectorstore()
        if vs is not None:
            try:
                # Import Document class — try multiple paths
                try:
                    from langchain.schema import Document
                except ImportError:
                    try:
                        from langchain_core.documents import Document
                    except ImportError:
                        from langchain_community.docstore.document import Document
                _delete_vectors(vs, name)
                splitter = _splitter()
                parts = splitter.split_text(text)
                docs = [Document(page_content=p, metadata={"source": name}) for p in parts]
                ids = [name + "::" + str(i) for i in range(len(docs))]
                if docs:
                    vs.add_documents(docs, ids=ids)
                chunks = max(1, len(docs))
                print(f"[RAG-Store] ✅ Indexed '{name}' → {chunks} chunk(s)")
            except Exception as exc:
                print(f"[RAG-Store] ❌ Vector indexing failed: {exc}")
                import traceback; traceback.print_exc()
                # Fall back to in-memory
                _MEM[name] = {"text": text, "modified": time.time()}
                chunks = max(1, (len(text) + 511) // 512)
            # The robot retrieval path (RAGEngine) caches query results and
            # latches `_available=False` when it started on an empty DB. After
            # adding a doc into the SHARED vector store, clear that cache and
            # mark it available so the new content is retrievable immediately,
            # without a server restart (Issue 1).
            try:
                _eng = _engine_ref.get("engine")
                if _eng is not None:
                    _eng.clear_cache()
                    _eng._available = True
            except Exception:
                pass
        else:
            _MEM[name] = {"text": text, "modified": time.time()}
            chunks = max(1, (len(text) + 511) // 512)
    return {"filename": name, "chunks": chunks}


def update(name, text):
    with _lock:
        return add(name, text)


def delete(name):
    with _lock:
        try:
            p = _data_path(name)
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass
        vs = _vectorstore()
        if vs is not None:
            _delete_vectors(vs, name)
            try:
                _eng = _engine_ref.get("engine")
                if _eng is not None:
                    _eng.clear_cache()
            except Exception:
                pass
        else:
            _MEM.pop(name, None)
    return {"deleted": name}


def get(name):
    try:
        p = _data_path(name)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return {"text": f.read(), "modified": os.path.getmtime(p)}
    except Exception:
        pass
    d = _MEM.get(name)
    if d:
        return {"text": d["text"], "modified": d["modified"]}
    return None


def stats():
    cfg = _cfg()
    docs = []
    total = 0
    # Try engine ref first (avoids loading embeddings twice)
    vs = _vectorstore(force_reload=(_VS["vs"] is None and _VS["ok"] is not True))
    if vs is not None:
        try:
            col = vs._collection
            got = col.get(include=["metadatas"])
            counts = {}
            for md in (got.get("metadatas") or []):
                src = (md or {}).get("source", "unknown")
                counts[src] = counts.get(src, 0) + 1
            for src, c in counts.items():
                total += c
                size = 0
                try:
                    p = os.path.join(cfg["data_dir"], src)
                    if os.path.exists(p):
                        size = os.path.getsize(p)
                except Exception:
                    pass
                docs.append({"filename": src, "chunks": c, "size_bytes": size, "modified": 0})
        except Exception as exc:
            print(f"[RAG-Store] stats error: {exc}")
            return {"error": str(exc), "document_count": 0, "chunk_count": 0, "documents": []}
    else:
        for name, d in _MEM.items():
            c = max(1, (len(d["text"]) + 511) // 512)
            total += c
            docs.append({
                "filename": name, "chunks": c,
                "size_bytes": len(d["text"].encode("utf-8")), "modified": d["modified"],
            })
    return {
        "collection": cfg["collection"],
        "document_count": len(docs),
        "chunk_count": total,
        "embedding_model": os.path.basename(str(cfg["embedding_model"])),
        "documents": docs,
        "settings": SETTINGS,
    }


def query(text):
    text = (text or "").strip()
    results = []
    if not text:
        return {"results": results}
    k = int(SETTINGS.get("top_k", 5) or 5)
    minrel = float(SETTINGS.get("min_relevance", 0.0) or 0.0)
    vs = _vectorstore()
    if vs is not None:
        try:
            hits = vs.similarity_search_with_relevance_scores(text, k=k)
            for doc, score in hits:
                if score is None or score >= minrel:
                    results.append({
                        "source": (doc.metadata or {}).get("source", "?"),
                        "text": doc.page_content,
                        "score": round(float(score or 0.0), 4),
                    })
        except Exception:
            pass
    else:
        ql = text.lower()
        for name, d in _MEM.items():
            pos = d["text"].lower().find(ql)
            if pos != -1:
                start = max(0, pos - 120)
                results.append({"source": name, "text": d["text"][start:pos + 240], "score": 1.0})
        results = results[:k]
    return {"results": results}


def rag_context(text):
    try:
        r = query(text)
    except Exception:
        return ""
    res = r.get("results") or []
    if not res:
        return ""
    blocks = []
    for it in res:
        blocks.append("[" + str(it.get("source", "?")) + "]\n" + str(it.get("text", "")))
    return "Relevant knowledge base context:\n" + "\n\n".join(blocks)


def set_settings(data):
    for key in ("chunk_size", "chunk_overlap", "top_k", "min_relevance"):
        if key in data and data[key] is not None:
            SETTINGS[key] = data[key]
    return SETTINGS


def reindex():
    try:
        from ingest import run_ingest
        run_ingest(reset=True)
        return {"ok": True, "message": "reindex complete"}
    except Exception as exc:
        return {"ok": True, "message": "reindex skipped: " + str(exc)}
