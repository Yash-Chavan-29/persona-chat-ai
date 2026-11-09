"""
app/core/vector_store.py
=========================
ChromaDB wrapper that stores WhatsApp dialogue pairs and retrieves
semantically similar examples for few-shot prompting.

The Hinglish Token Harmonizer is applied at BOTH index time and query
time so that phonetic variants (e.g. 'kyun' / 'kyu' / 'kyuu') always
map to the same vector neighbourhood.
"""
from __future__ import annotations

from typing import List

import chromadb
from chromadb.utils import embedding_functions

from app.core.parser import HinglishHarmonizer


class PersonaMemory:
    """
    Wraps a ChromaDB collection of (user_message → persona_response) pairs.
    """

    COLLECTION_NAME = "persona_pairs"
    EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

    def __init__(self, persist_dir: str = "./data/vector_db"):
        self.client = chromadb.PersistentClient(path=persist_dir)
        self.embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=self.EMBEDDING_MODEL
        )
        self.collection = self.client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            embedding_function=self.embed_fn,
            metadata={"hnsw:space": "cosine"},
        )

    # ── Indexing ──────────────────────────────────────────────────────────────

    def index_dialogue_pairs(
        self,
        dialogues: list,
        target_person: str,
    ) -> int:
        """
        Build (user → target_response) pairs from consecutive dialogue turns
        and upsert them into the ChromaDB collection.

        Returns the number of pairs indexed.
        """
        ids: List[str] = []
        documents: List[str] = []
        metadatas: List[dict] = []

        for i in range(len(dialogues) - 1):
            curr = dialogues[i]
            nxt = dialogues[i + 1]

            # Only index: non-target message immediately followed by target reply
            if (
                curr["sender"].strip().lower() != target_person.strip().lower()
                and nxt["sender"].strip().lower() == target_person.strip().lower()
            ):
                # Normalise the query text before embedding
                normalised_query = HinglishHarmonizer.normalize(curr["text"])
                doc_id = f"pair_{i}"
                ids.append(doc_id)
                documents.append(normalised_query)
                metadatas.append({"response": nxt["text"]})

        # ChromaDB has a maximum batch size of 5,461. Batch in chunks of 500 for safety and progress
        batch_size = 500
        for b_start in range(0, len(ids), batch_size):
            b_end = b_start + batch_size
            self.collection.upsert(
                ids=ids[b_start:b_end],
                documents=documents[b_start:b_end],
                metadatas=metadatas[b_start:b_end],
            )

        return len(ids)

    # ── Retrieval ─────────────────────────────────────────────────────────────

    def retrieve_similar_pairs(
        self,
        query: str,
        top_k: int = 4,
    ) -> List[dict]:
        """
        Return up to top_k {'query': str, 'response': str} pairs whose
        stored user-message is closest to the incoming query.

        The query is harmonised before searching.
        """
        # Normalise the incoming query the same way we normalised at index time
        normalised_query = HinglishHarmonizer.normalize(query)

        count = self.collection.count()
        if count == 0:
            return []

        actual_k = min(top_k, count)
        results = self.collection.query(
            query_texts=[normalised_query],
            n_results=actual_k,
        )

        pairs: List[dict] = []
        if results and results.get("documents"):
            for doc, meta in zip(
                results["documents"][0],
                results["metadatas"][0],
            ):
                pairs.append({"query": doc, "response": meta["response"]})

        return pairs

    # ── Utility ───────────────────────────────────────────────────────────────

    def count(self) -> int:
        """Return number of indexed pairs."""
        return self.collection.count()

    def reset(self) -> None:
        """Drop and recreate the collection (useful for fresh re-indexing)."""
        self.client.delete_collection(self.COLLECTION_NAME)
        self.collection = self.client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            embedding_function=self.embed_fn,
            metadata={"hnsw:space": "cosine"},
        )
