# Document RAG Assistant

[![CI](https://github.com/YOUR_GITHUB_USERNAME/document-rag-assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/YOUR_GITHUB_USERNAME/document-rag-assistant/actions/workflows/ci.yml)
*(replace `YOUR_GITHUB_USERNAME` after pushing to GitHub — the badge is dead until then)*

Full-stack RAG system: upload PDFs (digital or scanned), ask questions in natural
language, get streamed answers grounded strictly in the uploaded documents with
page-level citations.

## Stack

- **Backend**: FastAPI, LangGraph (agentic retrieval), ChromaDB (vectors),
  rank-bm25 (keyword search), PyMuPDF (PDF text), EasyOCR (scanned PDFs).
  Generation + evaluation default to Anthropic (`claude-haiku-4-5`); embeddings
  always use OpenAI (`text-embedding-3-small`) regardless of `LLM_PROVIDER`, since
  Anthropic doesn't offer an embeddings endpoint — see below.
- **Frontend**: React 18 + TypeScript, Vite, Tailwind CSS. Dark theme, gold accent (`#C9A84C`).

## Architecture

```
Upload -> PyMuPDF or EasyOCR -> chunk (500/50 overlap) -> OpenAI embeddings -> ChromaDB
Question -> hybrid search (vector + BM25 -> Reciprocal Rank Fusion)
         -> LangGraph agent (evaluate chunks -> rephrase & retry if insufficient, max 2x)
         -> streamed generation (SSE) -> faithfulness/relevance scoring -> stored
```

## Running locally

### Backend

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in OPENAI_API_KEY (always needed, for embeddings)
                        # and ANTHROPIC_API_KEY (default LLM_PROVIDER=anthropic)
uvicorn main:app --reload
```

Health check: `curl http://localhost:8000/health`

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Vite proxies `/api/*` to `http://localhost:8000` in dev (see `vite.config.ts`), so no
`.env` is needed locally. For production, set `VITE_API_BASE_URL` to the deployed
backend URL (see `.env.production.example`).

**Note on Vite version**: this project pins `vite@5` / `@vitejs/plugin-react@4`
deliberately. Vite 8's default Rolldown (Rust) bundler crashed in the sandbox this
was built in — if you hit a similar native-binary crash in your own environment,
this pin is why, and it's safe to try upgrading later.

## Testing

```bash
cd backend
pip install -r requirements.txt -r requirements-dev.txt
pytest --cov=services --cov=routers --cov=db --cov-report=term-missing
```

51 tests, ~89% coverage on `services`/`routers`/`db`. Every LLM and embedding call is
mocked (no API keys or network calls needed to run the suite) — this covers ingestion,
hybrid retrieval + RRF math, all three LangGraph agent branches (immediate success,
retry-then-succeed, max-iterations cap), the evaluator, the API layer including auth
and rate limiting, and both the OpenAI and Anthropic code paths in `services/llm.py`
(provider switching is asserted directly, not assumed). `services/ocr.py` and the
streaming-generator internals are intentionally excluded — those were verified
manually during development rather than unit tested, since exercising EasyOCR or a
real token stream meaningfully requires the actual model weights or a live API key.

CI (`.github/workflows/ci.yml`) runs this suite plus a frontend typecheck + build on
every push/PR once this is pushed to GitHub.

## API

- `POST /upload` — multipart PDF upload. Returns `{filename, chunk_count, method}`.
- `POST /query` — SSE stream. Body: `{question, document_filter?, history?}`, where
  `history` is `[{role: "user"|"assistant", content}, ...]` for prior turns (oldest
  first). Emits `{"type":"token","content":...}` events, then
  `{"type":"done","citations":[...],"eval":{...}}`. History is used to resolve
  follow-ups (a condense step rewrites e.g. "and the second point?" into a standalone
  search query — see `services/agent.py`) and to give the model conversational
  context when generating — it never becomes a source of facts on its own.
- `GET /documents` — list uploaded PDFs with chunk counts.
- `DELETE /documents/{filename}` — remove a document and its chunks.
- `GET /evaluation` — aggregated faithfulness/relevance scores + last 10 queries.

## Deployment

- **Backend -> Render**: `backend/render.yaml` (Blueprint). Set `OPENAI_API_KEY` /
  `ANTHROPIC_API_KEY` as secrets in the Render dashboard, and `ALLOWED_ORIGINS` to
  your Vercel URL once you have it.
- **Frontend -> Vercel**: import the `frontend/` directory as a Vite project (auto-detected),
  set `VITE_API_BASE_URL` to the Render URL.

### Known limitations (read before deploying)

- **Render free tier has no persistent disk.** `render.yaml` requests a 1GB disk,
  which requires a paid plan. Without it, ChromaDB's data and the evaluation SQLite
  file are wiped on every restart/redeploy/sleep cycle.
- **EasyOCR needs more RAM than Render's free 512MB tier gives you** (it's PyTorch-based).
  Scanned-PDF uploads will likely fail or time out on the free tier — either upgrade
  the plan or swap in a lighter OCR path (e.g. Tesseract) if you need to stay free.
- **Auth is opt-in.** Set `API_KEY` in the backend `.env` (and `VITE_API_KEY` in the
  frontend) before sharing a public URL — without it, every route except `/health` is
  open. Rate limits (`RATE_LIMIT_QUERY`, `RATE_LIMIT_UPLOAD`) are on by default
  (20/min and 10/min per IP) regardless of whether auth is configured.
- **Self-evaluation bias**: faithfulness/relevance scores use the same provider/model
  configured for generation (`LLM_PROVIDER`), which tends to rate itself favorably.
  Treat the eval dashboard as a directional signal, not a rigorous benchmark.
- **Embeddings are always OpenAI**, even when `LLM_PROVIDER=anthropic` — Anthropic
  doesn't have an embeddings API, so `OPENAI_API_KEY` is required either way.
