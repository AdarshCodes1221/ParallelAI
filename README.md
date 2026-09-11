# Parallel AI

Parallel AI is an autonomous multimodal AI agent and enterprise-style platform designed for local, self-hosted execution with resilient cloud fallback. It unifies conversational AI, native multimodal document extraction (PDFs, OCR scans, audio recordings, and YouTube transcripts), hybrid lexical-vector Retrieval Augmented Generation (RAG), multi-tenant session isolation, and persistent application state. Built around a FastAPI backend, a React 19 / Three.js 3D interactive frontend, PostgreSQL for authoritative persistence, and Redis Stack for hybrid search, Parallel AI executes deterministic multi-step tool workflows without requiring manual prompt engineering from the end user.

---

## Table of Contents

- [Overview](#overview)
- [Feature Matrix](#feature-matrix)
- [Architecture](#architecture)
- [Architecture Diagram](#architecture-diagram)
- [Core Request Flow](#core-request-flow)
- [Multimodal Pipelines](#multimodal-pipelines)
  - [PDF Document Parsing](#pdf-document-parsing)
  - [Optical Character Recognition (OCR)](#optical-character-recognition-ocr)
  - [Audio Transcription (Faster-Whisper)](#audio-transcription-faster-whisper)
  - [YouTube Transcript Extraction](#youtube-transcript-extraction)
- [RAG Pipeline](#rag-pipeline)
  - [Ingestion & Chunking](#ingestion--chunking)
  - [Query Expansion](#query-expansion)
  - [Hybrid Search (Lexical + Vector)](#hybrid-search-lexical--vector)
  - [Reciprocal Rank Fusion (RRF) & Contextual Focusing](#reciprocal-rank-fusion-rrf--contextual-focusing)
  - [Grounded Refusal & Retry Loop](#grounded-refusal--retry-loop)
- [Memory](#memory)
- [AI Provider Routing](#ai-provider-routing)
- [Authentication & Security](#authentication--security)
  - [Multi-Tenant Scoping](#multi-tenant-scoping)
  - [Argon2id & Token Digests](#argon2id--token-digests)
  - [Double-Submit CSRF Protection](#double-submit-csrf-protection)
  - [Rate Limiting & Upload Protection](#rate-limiting--upload-protection)
- [Data Storage](#data-storage)
  - [PostgreSQL (Authoritative Relational Store)](#postgresql-authoritative-relational-store)
  - [Redis Stack (Ephemeral Caching & RediSearch)](#redis-stack-ephemeral-caching--redisearch)
  - [Local Document Storage & S3 Adapter](#local-document-storage--s3-adapter)
- [Email / Password Reset](#email--password-reset)
- [Frontend](#frontend)
- [Backend](#backend)
- [Docker Services](#docker-services)
- [Project Structure](#project-structure)
- [Environment Configuration](#environment-configuration)
- [Running Locally](#running-locally)
  - [Prerequisites](#prerequisites)
  - [Step-by-Step Launch with Docker Compose](#step-by-step-launch-with-docker-compose)
  - [Manual Local Development](#manual-local-development)
- [API Overview](#api-overview)
  - [Authentication Endpoints](#authentication-endpoints)
  - [Agent & Interaction Endpoints](#agent--interaction-endpoints)
  - [Standalone Tool Endpoints](#standalone-tool-endpoints)
  - [Document & Session Management](#document--session-management)
- [Data Isolation](#data-isolation)
- [Development Notes](#development-notes)
- [Troubleshooting](#troubleshooting)
- [Future Improvements](#future-improvements)
- [License](#license)

---

## Overview

Modern AI applications often struggle to bridge the gap between unstructured local files and reliable conversational reasoning. Simple wrappers around proprietary APIs introduce privacy risks, lack offline resiliency, and frequently hallucinate when presented with domain-specific files.

**Parallel AI** solves these challenges by providing a unified, self-hostable system that executes complex tasks across heterogeneous data streams:

1. **Conversational AI with Dynamic Planning:** Rather than relying on rigid chatbot scripts, an intent classifier dynamically identifies required tools (parsers, search, summarizers, sentiment engines) and constructs a directed tool plan.
2. **Local & Private Execution:** Primary inference and embeddings run locally using [Ollama](https://ollama.com) (`llama3.2:3b` and `nomic-embed-text`), speech-to-text runs locally via [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper), and optical character recognition executes on-device via [Tesseract](https://github.com/tesseract-ocr/tesseract).
3. **Hybrid RAG Pipeline:** Context retrieval avoids single-strategy failures by executing simultaneous full-text lexical queries and $K$-nearest-neighbor cosine vector searches over Redis Stack, fusing them through Reciprocal Rank Fusion (RRF).
4. **Authoritative Relational Persistence:** All authentication, chat sessions, message histories, and document metadata are stored durably in PostgreSQL 16 using strict multi-tenant constraints.
5. **Multi-User Tenant Isolation:** Documents, embeddings, chat sessions, and audit events are strictly partitioned by `tenant_id` and `user_id`. One tenant's data cannot be queried, listed, or retrieved by another user.
6. **Graceful Fallbacks:** If local hardware is constrained or the primary local LLM encounters errors, the built-in provider router safely fails over to configured cloud providers (Google Gemini or Groq) while preventing namespace model collisions.

---

## Feature Matrix

| Feature | Implementation Status | Real Mechanism in Codebase |
| :--- | :---: | :--- |
| **Normal AI Chat** | Implemented | Direct multi-turn chat via `/api/agent` with context-aware intent resolution |
| **Streaming Responses (SSE)** | Implemented | `StreamingResponse` emitting `init`, `plan`, `trace`, `token`, `cost_update`, and `done` events |
| **PostgreSQL Persistence** | Implemented | PostgreSQL 16 schema (`tenants`, `users`, `sessions`, `chats`, `messages`, `documents`, `audit_events`) |
| **Redis Stack Hybrid Retrieval** | Implemented | RediSearch index `idx:chunks` combining lexical query matching and vector KNN cosine search |
| **Reciprocal Rank Fusion (RRF)** | Implemented | Fuses lexical and vector candidate ranks with $k=60$ factor; multi-query variant aggregation |
| **Contextual Evidence Focusing** | Implemented | `_focus_rag_evidence()` isolates matching sentences from retrieved chunks for low-parameter local models |
| **Grounded Refusal & Retry** | Implemented | Two-tier validation checking candidate chunk overlap; grounded retry prevents false claims |
| **PDF Extraction** | Implemented | Dual-layer extraction: `pdfplumber` for structured layout and `PyMuPDF` (`fitz`) for fallback/metadata |
| **OCR for Scans & Images** | Implemented | Local Tesseract OCR engine with confidence thresholding; Gemini Vision API fallback |
| **Audio Transcription** | Implemented | Local Faster-Whisper base model (`int8` CPU quantization) pre-cached in Docker image |
| **YouTube Ingestion** | Implemented | `youtube-transcript-api` extracting timestamped snippets with Gemini fallback; deterministic UUIDs |
| **Document Summarization** | Implemented | Standalone `/api/summary` and workflow summarizer tool with token-budgeted prompt construction |
| **Sentiment Analysis** | Implemented | Structured sentiment classification (`positive`, `negative`, `neutral`) with confidence and reasoning |
| **Code Analysis** | Implemented | `/api/code-analysis` providing bug detection, time/space complexity, and optimization advice |
| **Authentication & Sessions** | Implemented | Argon2id password hashing, HTTP-only secure cookies, and SHA-256 session token hashing |
| **CSRF Defense** | Implemented | Double-submit cookie pattern (`csrf_token` cookie + `X-CSRF-Token` header) |
| **Email & Password Reset** | Implemented | Mailpit for local development, standard SMTP for production, single-use SHA-256 reset tokens |
| **Local LLM Inference** | Implemented | Local Ollama endpoint running `llama3.2:3b` via HTTP APIs |
| **Local Embeddings** | Implemented | `nomic-embed-text` generating 768-dimensional float embeddings locally |
| **AI Provider Routing** | Implemented | Provider router cycling: `Ollama` $\to$ `Gemini` $\to$ `Groq` with automated model identifier remapping |
| **Upload Size Guard** | Implemented | Configurable `MAX_UPLOAD_SIZE_MB` (default 50MB) with HTTP 413 Payload Too Large enforcement |

---

## Architecture

Parallel AI is divided into clear functional boundaries:

- **Presentation Layer (Frontend):** React 19 single-page application built with TypeScript, Tailwind CSS, and Vite. Includes an interactive 3D canvas driven by Three.js, React Three Fiber, and GSAP that animates an avatar through idle, thinking, speech, and completion states.
- **Application Server (Backend):** FastAPI asynchronous service running on Python 3.10 with Starlette ASGI middleware. Handles security headers, CSRF validation, rate limiting, SSE streaming, and file upload lifecycles.
- **Agent Orchestrator (`AgentWorkflow`):** A multi-step state engine that classifies intent, detects referenced entities, schedules concurrent tool executions (PDF parser, OCR, Whisper STT, YouTube fetcher), manages RAG context, and formats citations.
- **Relational Data Tier (PostgreSQL):** Authoritative database managing multi-tenant identity, credential digests, chat sessions, message transcripts, and document ownership metadata.
- **Vector & Lexical Search Tier (Redis Stack):** High-speed indexing layer storing document chunk embeddings, metadata tags, and inverted text indexes.
- **Local Machine Learning Workers:** On-premise workers inside Docker or host machine:
  - *Faster-Whisper*: Pre-downloaded Whisper base model executing on CPU via `ctranslate2`.
  - *Tesseract OCR*: Linux binary installed via Poppler and Tesseract packages for OCR extraction.
  - *Ollama*: Host daemon providing LLM token generation and nomic vector embeddings.
- **Mail Delivery (Mailpit / SMTP):** Mailpit container running SMTP on port 1025 and an inspector web UI on port 8025 for password recovery workflows.

---

## Architecture Diagram

```mermaid
flowchart TD
    subgraph Client["Client Browser"]
        USER["User / Browser"]
        FE["React 19 + TypeScript + Vite"]
        THREE["Three.js 3D Robot Avatar"]
        FE --- THREE
    end

    subgraph Gateway["Application Layer (FastAPI)"]
        API["FastAPI App (:8000)"]
        SEC["Security Headers & CSRF Middleware"]
        RATE["Token Bucket Rate Limiter"]
        ROUTER["API Routes (/api/*)"]
        
        API --> SEC --> RATE --> ROUTER
    end

    subgraph CoreEngine["Agent & RAG Core"]
        RESOLVER["QueryContextResolver"]
        WORKFLOW["AgentWorkflow State Machine"]
        RAG["RAGService (Hybrid RediSearch)"]
        PROV["ProviderRouter"]
        
        ROUTER --> RESOLVER
        ROUTER --> WORKFLOW
        WORKFLOW --> RAG
        WORKFLOW --> PROV
    end

    subgraph IngestionEngines["Multimodal Ingestion Pipelines"]
        PDF_ENG["PDFParser (pdfplumber + PyMuPDF)"]
        OCR_ENG["OCRService (Tesseract OCR)"]
        WHISPER_ENG["AudioTranscriber (Faster-Whisper int8)"]
        YT_ENG["YouTubeFetcher (Direct API)"]
        
        WORKFLOW --> PDF_ENG
        WORKFLOW --> OCR_ENG
        WORKFLOW --> WHISPER_ENG
        WORKFLOW --> YT_ENG
    end

    subgraph LLMProviders["Inference Providers"]
        OLLAMA["Host Ollama (:11434)\nllama3.2:3b & nomic-embed-text"]
        GEMINI["Google Gemini Cloud Fallback\ngemini-2.5-flash"]
        GROQ["Groq Cloud Fallback\nllama-3.3-70b-versatile"]
        
        PROV -->|Primary / Local| OLLAMA
        PROV -->|Fallback 1| GEMINI
        PROV -->|Fallback 2| GROQ
    end

    subgraph StorageTier["Data & Persistence Tier"]
        PG[("PostgreSQL 16\n(Authoritative State)")]
        REDIS[("Redis Stack\n(idx:chunks RediSearch)")]
        DISK[("Local Storage Volume\n(/app/storage)")]
        MAIL[("Mailpit SMTP\n(:1025 / UI :8025)")]
    end

    USER <-->|HTTP / SSE Stream| FE
    FE <-->|REST API + SSE| API
    
    ROUTER <-->|Tenants, Users, Chats, Docs| PG
    RAG <-->|KNN Vector + Lexical Search| REDIS
    PDF_ENG -->|Store Original| DISK
    OCR_ENG -->|Store Original| DISK
    WHISPER_ENG -->|Store Original| DISK
    
    ROUTER -->|Password Reset Emails| MAIL
```

---

## Core Request Flow

When a user submits an interaction in the chat interface:

1. **Transport & Authentication:**
   - The browser dispatches a `POST /api/agent` multipart form request containing the user prompt, active `session_id`, target model, and optional file attachments.
   - The server validates session credentials from the `session_token` HTTP-only cookie and asserts tenant ownership.
2. **Document Ingestion (if files attached):**
   - Attached files are saved to `/app/storage/<document_id>/<filename>`.
   - Modality is detected (`application/pdf`, `image/*`, `audio/*`).
   - A document record is upserted into PostgreSQL with status `PROCESSING`.
   - The appropriate parser extracts the full text and metadata blocks.
   - Chunks are vectorized using `nomic-embed-text` and indexed into Redis RediSearch under `@document_id` and `@user_id`.
   - PostgreSQL is updated to `READY` with chunk and page counts.
3. **Query Context Resolution:**
   - `QueryContextResolver` analyzes the prompt against current session documents.
   - Contextual signals (e.g., questions asking about "GPA", "the video", "lyrics", "the speaker", or explicit document references) selectively activate RAG retrieval for relevant document IDs, preventing unrelated files from polluting the prompt.
4. **Intent Detection & Planning:**
   - An intent model evaluates the query and required tools (e.g., `["pdf_parser", "rag_search"]` or `["youtube_fetcher"]`).
5. **RAG Execution (if active):**
   - Query expansion produces variant lexical phrases.
   - Parallel RediSearch queries compute lexical BM25-like scores and vector KNN cosine distances.
   - RRF ranks top candidates.
   - Evidence focusing trims retrieved chunks to the exact sentences answering the question.
6. **Provider Invocation & Grounded Response:**
   - `ProviderRouter` formats the system instruction and retrieved context, dispatching to Ollama `llama3.2:3b`.
   - If the candidate chunks lack factual support, the model returns a grounded refusal rather than hallucinating.
7. **Server-Sent Events (SSE) Streaming:**
   - Tokens stream in real time to the browser.
   - Cost accounting and tool execution traces are transmitted before the connection closes with `type: done`.

---

## Multimodal Pipelines

### PDF Document Parsing
- **Engine:** `pdfplumber` paired with `PyMuPDF` (`fitz`).
- **Mechanism:** Text is extracted per page along with bounding box data and font characteristics. If tables are present, structure is converted into formatted text blocks.
- **Failover:** If a PDF contains scanned raster pages with no embedded fonts, the pipeline marks pages for OCR extraction.

### Optical Character Recognition (OCR)
- **Engine:** Tesseract 5 (`pytesseract`) supported by Poppler rendering utilities.
- **Preprocessing:** Images are standardized using Pillow (`PIL`), converting RGB channels, sharpening, and evaluating text density.
- **Cloud Fallback:** When image resolution or noise drops Tesseract confidence below threshold, the request routes to Google Gemini Vision (`gemini-2.5-flash`) if an API key is present.

### Audio Transcription (Faster-Whisper)
- **Engine:** `faster-whisper` (version 1.1.1) running `whisper-base` quantized to `int8` on CPU.
- **Packaging:** The base model weights are baked directly into the Docker image during build and mounted via the `whisper_cache` named volume to ensure **100% offline transcription** without downloading weights at runtime.
- **Output:** Returns full transcription text, language detection, duration in seconds, and word-level segment metadata.

### YouTube Transcript Extraction
- **Engine:** `youtube-transcript-api` with automatic video ID extraction.
- **Mechanism:** Direct retrieval of official or automatically generated subtitle tracks, preserving timestamp snippets (`start`, `duration`, `text`).
- **Identity Architecture:** Every YouTube ingestion generates a valid RFC 4122 deterministic UUID5 (`youtube:<user_id>:<session_id>:<url>`). The raw video ID (e.g. `RBumgq5yVrA`) is stored strictly in metadata.
- **Idempotency:** Re-submitting the same URL within the same chat session updates the existing document record in PostgreSQL and purges outdated Redis chunks without throwing unique constraint exceptions.

---

## RAG Pipeline

```
Raw Document / Transcript
          │
          ▼
┌──────────────────┐
│  Chunking Engine │ (200-word sliding window / 40-word overlap)
└─────────┬────────┘
          │
          ▼
┌──────────────────┐
│ nomic-embed-text │ (768-dimensional dense vectors)
└─────────┬────────┘
          │
          ▼
┌──────────────────┐
│   Redis Stack    │ HSET chunk:{id}
│    RediSearch    │ document_id, user_id, session_id, text, vector
└──────────────────┘
```

### Ingestion & Chunking
Text extracted from documents, audio transcripts, or YouTube videos is segmented using a sliding window chunker (default 200 words with 40-word overlap). Timestamped sources (Whisper audio and YouTube) preserve `timestamp_start` and `timestamp_end` within structured `EvidenceBlock` items.

### Query Expansion
Before retrieval, `QueryExpander` evaluates the input question and generates keyword-rich morphological variants, synonym expansions, and hyphenated variations to ensure lexical coverage.

### Hybrid Search (Lexical + Vector)
Parallel AI queries Redis Stack using two simultaneous query modes:
1. **Lexical RediSearch Query:**
   ```redis
   FT.SEARCH idx:chunks "@user_id:{user_uuid} @document_id:{doc_uuid} @text:(term1 | term2 | variant)"
   ```
2. **Vector KNN RediSearch Query:**
   ```redis
   FT.SEARCH idx:chunks "(@user_id:{user_uuid} @document_id:{doc_uuid})=>[KNN 40 @embedding $query_vec AS score]" PARAMS 2 query_vec <bytes>
   ```

### Reciprocal Rank Fusion (RRF) & Contextual Focusing
Candidate results from both searches are combined using RRF scoring:
$$RRF(d) = \sum_{m \in \{\text{lexical}, \text{vector}\}} \frac{1}{k + r_m(d)} \quad (k = 60)$$
Top-ranked chunks pass through `_focus_rag_evidence()`, which computes lexical token overlaps per sentence and extracts only the relevant sentences surrounding the answer. This prevents context saturation when small local models (`llama3.2:3b`) process long chunks.

### Grounded Refusal & Retry Loop
If the retrieved evidence lacks semantic correlation with the user's question, the workflow initiates a grounded validation check. If the candidate chunks do not support the query, the engine returns an explicit refusal (e.g., *"No such information found in the provided content"*), preventing hallucination.

---

## Memory

Parallel AI separates short-term conversational context from long-term authoritative history:

- **Session Context Window:** When conversational follow-up questions are detected (e.g., *"what did he say about that?"* or *"summarize what I said"*), the workflow pulls recent turns directly from PostgreSQL `messages` for that session.
- **Persistent Chat Storage:** Every message exchange (user input and assistant answer) is committed durably to the PostgreSQL `messages` table associated with `chat_id`, `tenant_id`, and `user_id`.
- **Client-Side Cache Scrubbing:** On application startup, the Zustand store automatically scrubs stale tokens or cross-user message states from browser `localStorage`, ensuring clean authentication boundaries.

---

## AI Provider Routing

Parallel AI provides a multi-provider fallback hierarchy configured in `ProviderRouter`:

```
┌─────────────────────────────────────────────────────────┐
│               1. Primary: Local Ollama                  │
│             llama3.2:3b / nomic-embed-text              │
└───────────────────────────┬─────────────────────────────┘
                            │ (On failure / unavailable)
                            ▼
┌─────────────────────────────────────────────────────────┐
│            2. Cloud Fallback: Google Gemini             │
│                    gemini-2.5-flash                     │
└───────────────────────────┬─────────────────────────────┘
                            │ (On failure / no key)
                            ▼
┌─────────────────────────────────────────────────────────┐
│              3. Cloud Fallback: Groq Cloud              │
│                llama-3.3-70b-versatile                  │
└─────────────────────────────────────────────────────────┘
```

### Automated Model Identifier Remapping
To prevent breaking external APIs, `ProviderRouter` automatically maps internal model names to provider-specific identifiers:
- Requests routed to **Ollama** always map to `llama3.2:3b`.
- Requests routed to **Gemini** map to `gemini-2.5-flash` (ensuring local model tags like `llama3.2:3b` are never sent to Google APIs).
- Requests routed to **Groq** map to `llama-3.3-70b-versatile`.

---

## Authentication & Security

### Multi-Tenant Scoping
Every user belongs to a `tenant_id`. Every chat session, stored message, document upload, and Redis chunk stores both `tenant_id` and `user_id`. Queries in PostgreSQL and RediSearch always enforce ownership filters:
```sql
SELECT * FROM documents WHERE user_id = %s AND session_id = %s;
```
A user cannot access, read, or search documents owned by another account.

### Argon2id & Token Digests
- Passwords are encrypted using **Argon2id** (`argon2-cffi`) with secure salt generation.
- Raw session tokens and password reset tokens **never touch the database**. The server generates cryptographically secure 32-byte tokens via `secrets.token_urlsafe(32)`, sets them in HTTP-only cookies or email links, and stores only their **SHA-256 digests** in the database.

### Double-Submit CSRF Protection
State-modifying endpoints (`POST`, `PUT`, `DELETE`) require double-submit CSRF verification:
1. The server sets a `csrf_token` cookie on login/signup.
2. The frontend reads the cookie and transmits it via the `X-CSRF-Token` request header.
3. FastAPI dependency `verify_csrf` asserts that the header matches the cookie value.

### Rate Limiting & Upload Protection
- Auth endpoints (`/login`, `/signup`, `/forgot-password`, `/reset-password`) feature IP-based and user-based token bucket rate limiters configured via environment variables.
- File uploads are validated before processing. Content length headers and stream byte counters reject files exceeding `MAX_UPLOAD_SIZE_MB` (HTTP 413).

---

## Data Storage

### PostgreSQL (Authoritative Relational Store)
PostgreSQL 16 serves as the primary system of record.
- **Tables:**
  - `tenants`: Multi-tenant organization accounts.
  - `users`: User profiles, Argon2id password hashes, roles.
  - `sessions`: Active login sessions with SHA-256 token digests, IP addresses, user agents, and expiry timestamps.
  - `password_reset_tokens`: Reset tokens with 1-hour expiry and single-use `used_at` markers.
  - `chats`: Conversation threads tied to `user_id` and `tenant_id`.
  - `messages`: Chronological chat messages tagged by role (`user`, `assistant`, `system`).
  - `documents`: Authoritative document metadata with RFC 4122 UUID keys, file size, checksum, status, and JSONB metadata.
  - `audit_events`: Security audit trail capturing signups, logins, and administrative actions.

### Redis Stack (Ephemeral Caching & RediSearch)
Redis Stack operates as a real-time retrieval and search accelerator:
- **RediSearch Index (`idx:chunks`):** Indexes document text chunks, vector embeddings, and tenant metadata tags.
- **Active Document Sets:** Tracks active document UUIDs per session (`session:<id>:documents`) and per user (`user:<id>:documents`).

### Local Document Storage & S3 Adapter
- **Local Filesystem:** Uploaded original files are stored under `/app/storage/<document_id>/<filename>` inside a persistent Docker volume (`document_storage`).
- **S3 / MinIO Adapter (`ObjectStorage`):** An optional S3 client via `boto3`. If `S3_BUCKET` is configured, files are mirrored to object storage; otherwise, the system operates seamlessly using local volume storage.

---

## Email / Password Reset

Password reset operations follow an asynchronous token delivery workflow:

1. User requests password reset via `POST /api/auth/forgot-password`.
2. The server generates a random token, commits the SHA-256 hash to PostgreSQL with a 1-hour TTL, and generates a single-use URL:
   ```
   http://localhost:5173/reset-password?token=<raw_token>
   ```
3. **Delivery Mechanism (`EmailProvider`):**
   - **Local Development / Docker:** Transmits through **Mailpit** on SMTP port 1025. Developers can view formatted HTML emails by visiting `http://localhost:8025`. If no SMTP server is configured, the reset link prints directly to the console log.
   - **Production:** Transmits via authenticated TLS/STARTTLS SMTP (e.g. Amazon SES, SendGrid, Mailgun) using configured `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, and `SMTP_PASSWORD`.
4. User submits the new password with the token via `POST /api/auth/reset-password`. The token is marked `used_at` and all prior user sessions are revoked.

---

## Frontend

The frontend is located in the `frontend/` directory and is built using:
- **React 19 & TypeScript:** Strict typing across all API contracts, chat messages, tool execution steps, and session states.
- **Vite:** High-performance local bundler with proxy support.
- **Tailwind CSS & Lucide Icons:** Clean, modern dark-mode enterprise UI.
- **Three.js & React Three Fiber:** Renders an interactive 3D robot avatar (`RobotCanvas`) displaying dynamic visual states:
  - `idle`: Calm ambient hovering.
  - `thinking`: Pulse glowing and rotational movement during agent planning and RAG search.
  - `audio`: Soundwave audio reactivity during speech synthesis.
  - `done`: Smooth transition back to resting state.
- **Zustand (`agentStore.ts`):** Centralized state management controlling session history, file uploads, SSE stream consumption, modal state, and CSRF token propagation.

---

## Backend

The backend is located in the `backend/` directory and is built using:
- **FastAPI:** High-throughput ASGI framework with asynchronous route handlers.
- **Agent Workflow Engine (`backend/agent/workflow.py`):** Coordinates tool execution, RAG context resolution, and generation fallback.
- **Services Architecture (`backend/services/`):** Clean separation of concerns across specialized services:
  - `auth_service.py` & `session_service.py`: Identity, tokens, and cookie handling.
  - `document_service.py`: Document lifecycle and persistence.
  - `rag_service.py`: Hybrid lexical-vector search and RRF.
  - `pdf_parser.py`, `ocr_service.py`, `audio_transcriber.py`, `youtube_fetcher.py`: Modality extractors.
  - `summarizer.py`, `sentiment.py`, `code_analyzer.py`: Standalone intelligence tools.
  - `providers/router.py`: LLM failover management.

---

## Docker Services

The complete multi-container stack is defined in `docker-compose.yml`:

| Service | Container Image | Host Ports | Purpose |
| :--- | :--- | :--- | :--- |
| **backend** | Custom Dockerfile (`python:3.10-slim`) | `8000:8000` | FastAPI application server, parsers, and agent orchestrator |
| **frontend** | Custom Dockerfile (`node:20` $\to$ NGINX) | `5173:80` | Production build of React 19 single-page application |
| **postgres** | `postgres:16-alpine` | `5432:5432` | Authoritative relational store (users, sessions, documents) |
| **redis** | `redis/redis-stack-server:latest` | `6379:6379` | RediSearch vector & lexical indexing engine |
| **mailpit** | `axllent/mailpit:latest` | `8025:8025`<br>`1025:1025` | Local development SMTP server and webmail inspector |

### Persistent Docker Volumes
- `postgres_data`: Persists PostgreSQL relational tables.
- `redis_data`: Persists Redis append-only / snapshot state.
- `document_storage`: Persists uploaded original files and parsed assets.
- `whisper_cache`: Persists Faster-Whisper base model weights to guarantee zero runtime downloads.
- `mailpit_data`: Persists development email inbox messages across restarts.

---

## Project Structure

```
parallel-ai/
├── docker-compose.yml           # Unified multi-container composition
├── .env.example                 # Root environment configuration reference
├── README.md                    # Project documentation
├── run_system_audit.py          # End-to-end integration test runner
├── backend/
│   ├── Dockerfile               # Backend container recipe with OCR & Whisper
│   ├── requirements.txt         # Python dependencies
│   ├── main.py                  # FastAPI app entry point & middleware
│   ├── core/
│   │   ├── config.py            # Typed environment settings
│   │   ├── postgres_store.py    # PostgreSQL connection and CRUD store
│   │   └── redis_store.py       # Redis client and JSON cache wrappers
│   ├── migrations/
│   │   └── 001_saas_auth.sql    # PostgreSQL schema migration
│   ├── agent/
│   │   ├── workflow.py          # State machine agent orchestrator
│   │   └── prompts.py           # System instructions and prompt templates
│   ├── routes/
│   │   ├── api.py               # Agent, tools, and document REST endpoints
│   │   └── auth.py              # Authentication, session, and reset routes
│   ├── services/
│   │   ├── auth_service.py      # Password verification and token generation
│   │   ├── session_service.py   # Chat session persistence
│   │   ├── document_service.py  # Document metadata and lifecycle
│   │   ├── rag_service.py       # RediSearch hybrid lexical/vector engine
│   │   ├── pdf_parser.py        # pdfplumber & PyMuPDF extractor
│   │   ├── ocr_service.py       # Tesseract OCR engine
│   │   ├── audio_transcriber.py # Faster-Whisper CPU transcriber
│   │   ├── youtube_fetcher.py   # YouTube transcript extractor
│   │   ├── summarizer.py        # Text summarization service
│   │   ├── sentiment.py         # Sentiment analysis classifier
│   │   ├── code_analyzer.py     # Code review and bug analysis
│   │   ├── email_provider.py    # SMTP & console email dispatcher
│   │   ├── object_storage.py    # Optional S3/MinIO adapter
│   │   └── providers/           # LLM router (Ollama, Gemini, Groq)
│   └── tests/                   # 145+ comprehensive Pytest verification tests
└── frontend/
    ├── Dockerfile               # Multi-stage frontend container build
    ├── package.json             # NPM dependencies
    ├── vite.config.ts           # Vite configuration
    └── src/
        ├── App.tsx              # Root React component
        ├── main.tsx             # DOM mount entry
        ├── store/
        │   └── agentStore.ts    # Zustand state management
        └── components/
            ├── auth/            # Login, Signup, Reset Password modals
            ├── layout/          # Header, Sidebar, ChatPanel
            └── robot/           # 3D Three.js Robot Canvas
```

---

## Environment Configuration

Create a `.env` file in the project root or in `backend/.env`. A complete template is provided below:

```ini
# ==============================================================================
# Database & Cache Infrastructure
# ==============================================================================
DATABASE_URL=postgresql://parallel:parallel@postgres:5432/parallel_ai
REDIS_URL=redis://redis:6379

# ==============================================================================
# Local AI (Ollama) Settings
# When running backend in Docker, point to host.docker.internal to reach host Ollama
# ==============================================================================
OLLAMA_URL=http://host.docker.internal:11434
OLLAMA_LLM_MODEL=llama3.2:3b
EMBEDDING_PROVIDER=ollama
EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_DIMENSION=768
PRIMARY_LLM_PROVIDER=ollama
LLM_MODE=offline

# ==============================================================================
# Cloud AI Provider Fallbacks (Optional)
# ==============================================================================
GEMINI_API_KEY=
GROQ_API_KEY=
FALLBACK_LLM_PROVIDER=gemini

# ==============================================================================
# Email & Password Reset (Mailpit for Local Dev)
# ==============================================================================
EMAIL_PROVIDER=smtp
SMTP_HOST=mailpit
SMTP_PORT=1025
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_TLS=false
EMAIL_FROM=no-reply@parallel-ai.local

# ==============================================================================
# Application & Security Settings
# ==============================================================================
FRONTEND_URL=http://localhost:5173
PASSWORD_RESET_BASE_URL=http://localhost:5173/reset-password
DOCUMENT_STORAGE_PATH=/app/storage
MAX_UPLOAD_SIZE_MB=50
COOKIE_SECURE=false
COOKIE_SAMESITE=lax
```

---

## Running Locally

### Prerequisites
1. **Docker & Docker Compose:** Install Docker Desktop (Windows/macOS) or Docker Engine with Compose plugin (Linux).
2. **Ollama:** Install [Ollama](https://ollama.com) on your host system.
   - Pull the required LLM model:
     ```bash
     ollama pull llama3.2:3b
     ```
   - Pull the required embedding model:
     ```bash
     ollama pull nomic-embed-text
     ```
   - Ensure Ollama is running and accessible on port `11434`.

### Step-by-Step Launch with Docker Compose

1. **Clone the repository:**
   ```bash
   git clone https://github.com/AdarshCodes1221/ParallelAI.git
   cd "ParallelAI"
   ```

2. **Verify host Ollama accessibility:**
   ```bash
   curl http://localhost:11434/api/tags
   ```

3. **Build and launch the complete stack:**
   ```bash
   docker compose up --build -d
   ```

4. **Verify container health:**
   ```bash
   docker compose ps
   ```
   All five services (`backend`, `frontend`, `postgres`, `redis`, `mailpit`) should report healthy status.

5. **Open the applications:**
   - **Parallel AI Web Interface:** [http://localhost:5173](http://localhost:5173)
   - **Backend OpenAPI Documentation:** [http://localhost:8000/docs](http://localhost:8000/docs)
   - **Backend Healthcheck:** [http://localhost:8000/health](http://localhost:8000/health)
   - **Mailpit Email Inspector:** [http://localhost:8025](http://localhost:8025)

---

### Manual Local Development

If you prefer to run services natively without containerizing Python and Node:

#### 1. Start Infrastructure Services Only
```bash
docker compose up postgres redis mailpit -d
```

#### 2. Run Backend
```bash
cd backend
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

#### 3. Run Frontend
```bash
cd frontend
npm install
npm run dev
```

---

## API Overview

### Authentication Endpoints

| Method | Path | Description | Authentication Required |
| :--- | :--- | :--- | :---: |
| `POST` | `/api/auth/signup` | Registers a new user account and tenant | No |
| `POST` | `/api/auth/login` | Authenticates user; issues session & CSRF cookies | No |
| `GET` | `/api/auth/me` | Retrieves the profile of the authenticated user | Cookie Session |
| `POST` | `/api/auth/forgot-password` | Dispatches password reset link via email provider | No |
| `POST` | `/api/auth/reset-password` | Consumes single-use reset token and updates password | No |
| `POST` | `/api/auth/change-password` | Updates password for authenticated user | Cookie + CSRF |
| `POST` | `/api/auth/logout` | Revokes current session and clears cookies | Cookie + CSRF |

### Agent & Interaction Endpoints

| Method | Path | Description | Authentication Required |
| :--- | :--- | :--- | :---: |
| `POST` | `/api/agent` | Dispatches agent workflow; returns Server-Sent Events stream | Cookie Session |
| `GET` | `/api/models` | Returns configured model registry and active providers | Cookie Session |

### Standalone Tool Endpoints

| Method | Path | Description | Authentication Required |
| :--- | :--- | :--- | :---: |
| `POST` | `/api/pdf` | Extracts raw text from an uploaded PDF | Cookie Session |
| `POST` | `/api/ocr` | Extracts raw text from an uploaded image via OCR | Cookie Session |
| `POST` | `/api/audio` | Transcribes an uploaded audio file using Faster-Whisper | Cookie Session |
| `POST` | `/api/youtube` | Fetches transcript and indexes a YouTube URL | Cookie Session |
| `POST` | `/api/summary` | Generates a structured summary of provided text | Cookie Session |
| `POST` | `/api/sentiment` | Performs sentiment analysis with confidence ratings | Cookie Session |
| `POST` | `/api/code-analysis` | Performs security and optimization code review | Cookie Session |
| `POST` | `/api/search` | Executes standalone hybrid lexical-vector search | Cookie Session |

### Document & Session Management

| Method | Path | Description | Authentication Required |
| :--- | :--- | :--- | :---: |
| `POST` | `/api/sessions` | Creates a new chat thread for the current user | Cookie + CSRF |
| `GET` | `/api/sessions` | Lists all chat sessions belonging to the user | Cookie Session |
| `GET` | `/api/sessions/{id}` | Retrieves session details and historical messages | Cookie Session |
| `DELETE` | `/api/sessions/{id}` | Deletes session and associated messages | Cookie + CSRF |
| `POST` | `/api/documents/upload` | Uploads, chunks, embeds, and indexes a document | Cookie + CSRF |
| `GET` | `/api/documents` | Lists all indexed documents for user or session | Cookie Session |
| `GET` | `/api/documents/{id}` | Retrieves metadata for a specific document | Cookie Session |
| `DELETE` | `/api/documents/{id}` | Deletes document and purges all RediSearch chunks | Cookie + CSRF |

---

## Data Isolation

Multi-user isolation is enforced at every layer of the architecture:

1. **Database Partitioning:**
   - Database queries filter strictly by `user_id` and `tenant_id`.
   - Foreign keys cascade deletion from `users` and `chats` down to `messages` and `documents`.
2. **Vector Index Partitioning:**
   - Every indexed chunk in Redis stores a `@user_id` tag field.
   - Vector and lexical queries are wrapped with mandatory user filters:
     ```
     (@user_id:{user_uuid} @document_id:{doc_uuid})
     ```
   - User B cannot retrieve chunks belonging to User A, even if querying with identical keywords or semantic queries.
3. **Session Ownership Enforcement:**
   - If User B attempts to access User A's `session_id`, the API enforces ownership validation and returns **HTTP 403 Forbidden** or **HTTP 404 Not Found**.

---

## Development Notes

### Running Automated Test Suites

The codebase includes an extensive automated test suite covering unit, integration, persistence, and multimodal RAG behavior.

1. **Run full pytest suite inside the backend container:**
   ```bash
   docker compose exec -T backend pytest tests/ -v
   ```
   *Expected Output: 145 passed test assertions.*

2. **Run the dedicated YouTube RAG integration suite:**
   ```bash
   docker compose exec -T backend pytest tests/test_youtube_chat_and_rag_pipeline.py -v
   ```
   *Expected Output: 10 passed test assertions.*

3. **Run the end-to-end system audit script:**
   ```bash
   python run_system_audit.py
   ```
   *Verifies live signup, login, Mailpit password reset, PDF upload, OCR image analysis, audio transcription, YouTube ingestion, and multi-user tenant isolation against running containers.*

---

## Troubleshooting

### 1. `uvicorn.protocols.utils.ClientDisconnected`
- **Cause:** Occurs when a browser cancels or closes an EventSource/SSE connection prematurely (e.g., navigating away or refreshing while streaming).
- **Resolution:** Parallel AI intercepts `ClientDisconnected`, `CancelledError`, and `GeneratorExit` in the streaming middleware and returns HTTP 499 cleanly without polluting server logs with stack traces.

### 2. Backend Cannot Connect to Ollama (`Connection Refused`)
- **Cause:** When running inside Docker on Windows or macOS, `localhost:11434` resolves to the backend container itself rather than the host machine.
- **Resolution:** Verify `OLLAMA_URL` in `docker-compose.yml` is set to `http://host.docker.internal:11434`. On Linux, ensure `add-host: "host.docker.internal:host-gateway"` is configured in `docker-compose.yml` if necessary.

### 3. PostgreSQL `InvalidTextRepresentation` (UUID Syntax)
- **Cause:** Historical code previously attempted to store non-standard document identifiers like `yt-<video_id>` directly into PostgreSQL UUID columns.
- **Resolution:** The platform enforces RFC 4122 UUIDs generated via `uuid.uuid5(uuid.NAMESPACE_URL, ...)` across all entities. Video IDs are strictly stored inside metadata JSON.

### 4. Tesseract OCR Missing Language Packs
- **Cause:** When running natively outside Docker, Tesseract language files may not be installed.
- **Resolution:** Install `tesseract-ocr` and `tesseract-ocr-eng` using your system package manager (`apt-get install tesseract-ocr tesseract-ocr-eng` on Ubuntu/Debian, or `brew install tesseract` on macOS).

---

## Future Improvements

- **Distributed Task Queuing:** Offload heavy audio transcription and multi-hundred-page document OCR to an asynchronous Celery or ARQ background worker queue.
- **Role-Based Access Control (RBAC):** Expand the current `owner`/`member` user roles into fine-grained permissions for enterprise document sharing.
- **Document Versioning:** Add automated diffing and revision histories for modified document uploads within existing chat sessions.
- **WebSocket Bi-Directional Streaming:** Support real-time audio duplexing for continuous voice-to-voice agent interaction.

---

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
