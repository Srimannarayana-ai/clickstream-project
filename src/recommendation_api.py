"""
Recommendation API — serves purchase suggestions from ChromaDB context.

Supports a local mock response path (USE_MOCK_LLM=true) or live Claude calls
when ANTHROPIC_API_KEY is set and USE_MOCK_LLM=false.

Run: uvicorn src.recommendation_api:app --reload --port 8090
"""

import os
from pathlib import Path
from typing import Any

import chromadb
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
CHROMA_DIR = os.getenv("CHROMA_PATH", str(BASE_DIR / "chroma_vault"))
COLLECTION_NAME = "realtime_user_contexts"
USE_MOCK_LLM = os.getenv("USE_MOCK_LLM", "true").lower() in ("true", "1", "yes")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-3-haiku-20240307")

# ── ChromaDB (same vault + collection as processor.py) ───────────────────────
_chroma = chromadb.PersistentClient(path=CHROMA_DIR)
_collection = _chroma.get_or_create_collection(name=COLLECTION_NAME)


# ── Request / response models ─────────────────────────────────────────────────
class RecommendationRequest(BaseModel):
    user_id: int = Field(..., ge=1, description="User to personalize for")
    question: str = Field(
        default="What products or categories should we recommend next?",
        min_length=1,
        max_length=500,
    )


class ContextItem(BaseModel):
    document: str
    metadata: dict[str, Any]


class RecommendationResponse(BaseModel):
    user_id: int
    mode: str
    context_count: int
    user_purchases: list[ContextItem]
    similar_purchases: list[ContextItem]
    recommendation: str


# ── Retrieval ─────────────────────────────────────────────────────────────────
def _fetch_user_purchases(user_id: int, limit: int = 10) -> list[ContextItem]:
    result = _collection.get(
        where={"user_id": user_id},
        include=["documents", "metadatas"],
        limit=limit,
    )
    items: list[ContextItem] = []
    for doc, meta in zip(result.get("documents") or [], result.get("metadatas") or []):
        if doc:
            items.append(ContextItem(document=doc, metadata=meta or {}))
    return items


def _fetch_similar_purchases(query_text: str, n_results: int = 5) -> list[ContextItem]:
    if not query_text.strip():
        return []
    result = _collection.query(
        query_texts=[query_text],
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )
    items: list[ContextItem] = []
    docs = (result.get("documents") or [[]])[0]
    metas = (result.get("metadatas") or [[]])[0]
    for doc, meta in zip(docs, metas):
        if doc:
            items.append(ContextItem(document=doc, metadata=meta or {}))
    return items


def _build_prompt(
    user_id: int,
    question: str,
    user_purchases: list[ContextItem],
    similar_purchases: list[ContextItem],
) -> str:
    user_block = "\n".join(f"- {c.document}" for c in user_purchases) or "(no purchases on record)"
    similar_block = "\n".join(f"- {c.document}" for c in similar_purchases) or "(none)"
    return f"""You are an e-commerce recommendation assistant.

User ID: {user_id}

This user's recent purchases:
{user_block}

Similar shoppers' purchases:
{similar_block}

Question: {question}

Give 2-3 concise, actionable product recommendations grounded ONLY in the purchase context above.
Mention platform or category patterns you observe. Keep under 150 words."""


def _mock_recommendation(
    user_id: int,
    user_purchases: list[ContextItem],
    similar_purchases: list[ContextItem],
) -> str:
    platforms = {c.metadata.get("platform", "unknown") for c in user_purchases}
    platform_hint = ", ".join(sorted(platforms)) if platforms else "unknown"
    similar_hint = similar_purchases[0].document if similar_purchases else "similar trending items"
    return (
        f"User {user_id} mostly shops on {platform_hint}. "
        f"Looking at their history and similar buyers ({similar_hint}), "
        f"I would recommend: (1) accessories tied to their last purchase category, "
        f"(2) a repeat-buy offer on {platform_hint}, "
        f"(3) a cross-sell item that similar shoppers bought next."
    )


def _claude_recommendation(prompt: str) -> str:
    if not ANTHROPIC_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY not set. Use mock mode (USE_MOCK_LLM=true) or add a key to .env",
        )
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    parts = [block.text for block in message.content if hasattr(block, "text")]
    return "\n".join(parts).strip() or "(empty response from Claude)"


# ── FastAPI ───────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Clickstream Recommendation API",
    description="Personalized recommendations from ChromaDB purchase context",
    version="1.0.0",
)


@app.get("/health")
def health():
    count = _collection.count()
    return {
        "status": "ok",
        "chroma_path": CHROMA_DIR,
        "collection": COLLECTION_NAME,
        "document_count": count,
        "llm_mode": "mock" if USE_MOCK_LLM else "anthropic",
    }


@app.get("/users/{user_id}/context")
def user_context(user_id: int, limit: int = 10):
    purchases = _fetch_user_purchases(user_id, limit=limit)
    if not purchases:
        raise HTTPException(status_code=404, detail=f"No purchase context for user_id={user_id}")
    query = purchases[-1].document
    similar = _fetch_similar_purchases(query, n_results=5)
    return {
        "user_id": user_id,
        "user_purchases": purchases,
        "similar_purchases": similar,
    }


@app.post("/recommendations", response_model=RecommendationResponse)
def recommend(body: RecommendationRequest):
    user_purchases = _fetch_user_purchases(body.user_id)
    if not user_purchases:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No ChromaDB context for user_id={body.user_id}. "
                "Run producer + processor first to ingest purchases."
            ),
        )

    query_doc = user_purchases[-1].document
    similar = _fetch_similar_purchases(query_doc, n_results=5)
    # Drop duplicate of same user's doc from similar results
    similar = [s for s in similar if s.metadata.get("user_id") != body.user_id][:5]

    prompt = _build_prompt(body.user_id, body.question, user_purchases, similar)

    if USE_MOCK_LLM:
        text = _mock_recommendation(body.user_id, user_purchases, similar)
        mode = "mock"
    else:
        text = _claude_recommendation(prompt)
        mode = "anthropic"

    return RecommendationResponse(
        user_id=body.user_id,
        mode=mode,
        context_count=len(user_purchases) + len(similar),
        user_purchases=user_purchases,
        similar_purchases=similar,
        recommendation=text,
    )
