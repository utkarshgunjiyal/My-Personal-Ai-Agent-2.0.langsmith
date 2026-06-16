# 🎬 AI Mentor — Demo Walkthrough

A 3-minute interview-ready demo flow that shows every flagship capability of
the platform. Use this script verbatim in an interview, or send the live link
to a recruiter and ask them to follow these steps.

**Live demo:** [https://multi-source-rag.preview.emergentagent.com](https://multi-source-rag.preview.emergentagent.com)

```
Demo account
  email:    admin@decision-engine.dev
  password: admin123
```

---

## 0. Sign in (15 seconds)

Login with the demo account above, or click **Continue with Google** for
one-tap OAuth sign-in. You land on a thread sidebar with the empty-state
"Ask the engine." panel.

> **What it demonstrates:** JWT email/password + Emergent Google OAuth
> sharing a unified user model, httpOnly cookies, bcrypt hashing.

---

## 1. Vanilla multi-agent question (30 seconds)

> **Ask:** *"Compare BM25 with dense vector retrieval. When does each win?"*

**What you'll see, in order:**

1. **Live pipeline** appears with **4 agents** (KB / GENERAL / WEB / ARXIV).
2. Each agent transitions `pending → running → done` independently. Latencies
   vary by source (KB is fast, WEB and ARXIV take longer because of external
   APIs).
3. **Judge scores** arrive — each candidate scored 0–10. The best is badged.
4. The **refiner** streams the final answer token-by-token.
5. **Below the answer:** click *"Agent trace · scores [...]"* to expand. Every
   candidate's full text, judge score, and elapsed ms is shown — so you can
   see *exactly* what each agent contributed.

> **What it demonstrates:** parallel agent fan-out via `asyncio.gather`,
> LLM-as-a-judge evaluation, answer refinement, full SSE observability.

---

## 2. Repeat the same question → **semantic cache hit** (5 seconds)

> **Ask the same question again** (or a paraphrase).

You'll see a **cyan "CACHE HIT" badge** with the cosine similarity score, and
the cached answer appears in ~10 ms — no agents run.

> **What it demonstrates:** per-user TF-IDF semantic cache hydrated from
> MongoDB on startup, cosine threshold ≥ 0.72, persistent across server
> restarts.

---

## 3. Upload a PDF → **5-agent pipeline + document intelligence** (45 seconds)

**Three ways to attach** — try all three:

- 📎 Click the **paperclip** in the composer
- 🖱️ **Drag-and-drop** a file onto the chat area (purple overlay appears)
- 📋 **Paste** an image directly from your clipboard

Drop any PDF — your resume, a research paper, an invoice, anything.

You'll see a chip appear with metadata:

```
📄  myfile.pdf  ·  6 KB  ·  8 chunks
```

For scanned PDFs you'll also see an **`OCR`** badge.

> **Ask:** *"Summarize this document for me in 5 bullets."*

**What you'll see now:**

1. The **`uploads_used`** event fires before any agent starts.
2. The pipeline shows **5 agents** — the new **purple "YOUR FILES"** agent
   (`thread_files`) appears.
3. The `thread_files` agent retrieves chunks via **hybrid BM25 + FAISS RRF
   fusion** over your document.
4. The judge typically picks `thread_files` as best (purple BEST badge),
   because the answer cites your filename and content.
5. The final synthesis quotes specifics from your file.

> **What it demonstrates:** dynamic agent activation, hybrid retrieval
> (sparse + dense + RRF fusion), per-thread FAISS persistence,
> hard-override that prevents LLM-judge bias against revealing
> user-owned content.

---

## 4. Drop an image → **vision + OCR + retrieval** (30 seconds)

Drop a screenshot, a photo of handwritten notes, a chart, or a receipt.

> **Ask:** *"What's the total amount on this receipt?"* / *"Transcribe the
> handwritten notes."* / *"What's the trend in this chart?"*

The image chip will show:

```
🖼  receipt.jpg  ·  240 KB  ·  vision  ·  OCR  ·  4 chunks
```

> **What it demonstrates:** parallel Tesseract OCR + gpt-4o vision
> description, automatic chunking + embedding, immediate availability for
> the next question on the thread.

---

## 5. Per-document summarize (10 seconds)

On any attachment chip, click the **bullet-list icon** (≡).

A modal opens with a structured markdown summary:

```
**TL;DR:** one-sentence overview
**Key points:** 5 concise bullets
**Entities / numbers worth noting:** ...
**Open questions / next actions:** ...
```

> **What it demonstrates:** purpose-built summarizer endpoint
> (`POST /api/uploads/{file_id}/summarize`) using all chunks of the document
> with a structured-output prompt.

---

## 6. Voice input + read-aloud (15 seconds)

- Click the **🎤 microphone** icon. Speak your question. Click again to
  stop. The transcript appears in the textarea — send it.
- After any assistant message, click the **🔊 speaker** icon next to the
  latency badge. The answer is read aloud.

> **What it demonstrates:** zero-cost voice via browser Web Speech API
> (STT + TTS) — gracefully degrades on browsers that don't support it,
> never auto-plays.

---

## 7. Restart resilience (the wow moment) (10 seconds)

1. Refresh the page.
2. Open the same thread from the sidebar.

**Everything is still there:**

- All messages
- All uploaded files (chips)
- All chunks (the engine still answers grounded questions about them)
- The conversation summary (if you had 10+ messages)

> **What it demonstrates:** complete MongoDB persistence + automatic FAISS
> reload from disk. If the `.index` file is missing, it is rebuilt from
> MongoDB chunks transparently — users never re-upload.

---

## 8. Conversation memory (advanced, 30 seconds)

Have a 10-message back-and-forth on a single thread. Around message 10,
watch the network panel — you'll see a **`summary_updated`** SSE event fire.

Now ask a vague follow-up like *"and what was the next thing I mentioned?"*

The engine remembers — because every agent prompt includes:

1. **Rolling LLM summary** (regenerated every 10 messages)
2. **Last 5 messages** (short-term)
3. **Retrieved document chunks** (per-thread)

> **What it demonstrates:** three-tier memory with delta-counter robustness
> (boundaries aren't skipped through cache hits), summary persisted in the
> `summaries` collection.

---

## 9. Dashboard (10 seconds)

Sidebar → **Dashboard** icon.

- Per-agent leaderboard (avg score, win count)
- Cache hit rate
- Weekly query volume
- Last 20 runs with judge scores

> **What it demonstrates:** the engine's own self-reported performance —
> measured by its own judge. Admin sees aggregated stats across users;
> regular users see only their own.

---

## 🎤 The interview talk track (45 seconds, optional)

> *"I built an agentic AI mentor that grounds every answer in either the
> knowledge base, the live web, arXiv, or — when the user uploads files — a
> per-thread FAISS index built from their own documents. PDFs are run through
> Tesseract OCR if the text layer is missing; images go through both
> Tesseract and a vision LLM. The 5 agents fan out concurrently, an
> LLM-as-a-judge scores each candidate 0–10, and a refiner synthesizes the
> final answer. The whole pipeline streams over Server-Sent Events. Everything
> is persisted in MongoDB — threads, messages, chunks, summaries, and the
> semantic cache. FAISS indices live on disk and are auto-rebuilt from Mongo
> chunks if they're ever missing, so users never have to re-upload.
> Conversation memory uses a three-tier composition: a rolling LLM summary
> regenerated every 10 messages, the last 5 messages verbatim, and the top
> retrieved chunks. The UI supports drag-drop, paste-image, voice input via
> Web Speech, and read-aloud. The whole stack is FastAPI + React + MongoDB +
> FAISS + fastembed (ONNX embeddings — no PyTorch dependency)."*

---

## 🛠️ Reset the demo

If you (or a recruiter) want a fresh state:

1. Log in.
2. Sidebar → delete the threads you've created.
3. Refresh.

Or just register a new account — every user has an isolated state.

---

Built to be the kind of project that gets you to the next interview round.
Good luck. 🚀
