# Document RAG Assistant

Full-stack RAG system: upload PDFs (digital or scanned), ask questions in natural
language, get streamed answers grounded strictly in the uploaded documents with
page-level citations.

## Stack

- **Backend**: FastAPI, LangGraph (agentic retrieval), ChromaDB (vectors),
  rank-bm25 (keyword search), PyMuPDF (PDF text), EasyOCR (scanned PDFs),
  OpenAI (`text-embedding-3-small`, `gpt-4o-mini`) / Anthropic (Claude) for generation.
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
cp .env.example .env   # fill in OPENAI_API_KEY (and ANTHROPIC_API_KEY if using Claude)
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

## API

- `POST /upload` — multipart PDF upload. Returns `{filename, chunk_count, method}`.
- `POST /query` — SSE stream. Body: `{question, document_filter?}`. Emits
  `{"type":"token","content":...}` events, then `{"type":"done","citations":[...],"eval":{...}}`.
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
- **No auth/rate limiting.** The API as built is open — add an API key check or rate
  limit before sharing a public URL, since every `/upload` and `/query` call spends
  your OpenAI/Anthropic credits.
- **Self-evaluation bias**: faithfulness/relevance scores use the same model
  (`gpt-4o-mini`) that generates the answers, which tends to rate itself favorably.
  Treat the eval dashboard as a directional signal, not a rigorous benchmark.
