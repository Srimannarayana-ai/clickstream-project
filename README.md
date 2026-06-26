# Real-Time Clickstream & AI Context Pipeline

![Python](https://img.shields.io/badge/Python-3.11-blue.svg)
![Apache Kafka](https://img.shields.io/badge/Apache%20Kafka-KRaft-black.svg)
![BigQuery](https://img.shields.io/badge/Google%20BigQuery-Warehouse-4285F4.svg)
![ChromaDB](https://img.shields.io/badge/ChromaDB-Vector%20Store-FF4B4B.svg)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED.svg)
![Apache Airflow](https://img.shields.io/badge/Apache%20Airflow-2.9-017CEE.svg)

## Overview

This project simulates how an e-commerce platform processes user activity in real time. It captures clickstream events as they happen, filters them down to purchases, and writes each purchase to two destinations at once:

- **ChromaDB** — a vector store, so an AI model can later retrieve similar user behavior for recommendations.
- **Google BigQuery** — a cloud data warehouse, so analysts can query the same data with SQL for dashboards and reporting.

This is called a **dual-fork** pattern: one event, two stores, two different downstream jobs. It mirrors how real data teams serve both AI/ML systems and business intelligence from the same event stream without maintaining separate pipelines.

This is a learning project built with free-tier tools. It runs locally with Docker, with the warehouse layer hosted on Google Cloud's free BigQuery sandbox.

---

## Architecture

```
Producer  →  Kafka  →  Processor  →  ┬─→  ChromaDB   (AI vector store)
(events)    (queue)   (filter +      │       ↓
                       validate)      │   Recommendation API (Phase 7)
                                      │       ↓
                                      │   Mock LLM / Claude
                                      └─→  BigQuery   (cloud warehouse)
                                              ↑
                                              │
                                    Airflow DAG (daily health check)
```

### Components

1. **Producer** (`src/producer.py`) — generates simulated clickstream events using the Faker library and publishes them to Kafka. It deliberately injects a small percentage of malformed records to test the pipeline's error handling.

2. **Kafka** — acts as the message queue between the producer and processor. It decouples the two, so if the processor slows down or restarts, events wait safely in the queue instead of being lost.

3. **Processor** (`src/processor.py`) — consumes events from Kafka, keeps only purchase events, validates them, then writes each valid event to both ChromaDB and BigQuery. Invalid records are routed to a dead-letter queue.

4. **ChromaDB** — stores each purchase as a vector embedding for AI-driven similarity search.

5. **BigQuery** — stores each purchase as a structured row in a cloud warehouse table for SQL analytics.

6. **Apache Airflow** — schedules and monitors warehouse health checks via DAGs in `dags/`. The producer and processor still run locally; Airflow tracks daily BigQuery validation runs, retries, and execution history in its UI.

7. **Recommendation API** (`src/recommendation_api.py`) — FastAPI service that reads purchase context from ChromaDB and returns LLM-generated recommendations. Defaults to **mock mode ($0)**; optional Anthropic Claude when configured.

### Verified Output

Purchase events landing in the BigQuery warehouse table, queried with SQL:

![BigQuery purchase events](./assets/bigquery_output.png)

---

## Phase 6 — Orchestration (Apache Airflow)

Phase 6 adds **scheduling and monitoring** for the BigQuery warehouse fork. Stream ingestion (Phases 1–5) is unchanged — producer and processor still run as local Python processes.

### What was added

| Item | Purpose |
|------|---------|
| `docker-compose.yml` — `airflow-postgres`, `airflow-init`, `airflow` | Airflow metadata DB, one-shot setup, scheduler + webserver |
| `dags/clickstream_pipeline_health.py` | Daily DAG that validates the warehouse table and summarizes recent purchases |
| `logs/` | Airflow runtime logs (gitignored except `.gitkeep`) |
| `google_cloud_default` connection | Auto-configured in Docker via `_AIRFLOW_CONN_GOOGLE_CLOUD_DEFAULT` |

### DAG: `clickstream_pipeline_health`

Runs on a **daily schedule** (`@daily`). Tasks run in order:

1. **`verify_warehouse_table`** — confirms `purchase_events` is reachable in BigQuery.
2. **`summarize_recent_purchases`** — counts purchases and latest `ingested_at` for the last 24 hours.

Both tasks use the `google_cloud_default` connection, which points to the mounted credentials file at `/opt/airflow/gcp_credentials.json` inside the container.

### Verified Output

Successful DAG run in the Airflow UI — both warehouse health tasks green:

![Airflow DAG success](./assets/airflow_dag_success.png)

### Running Phase 6

```bash
# 1. Start Docker (includes Airflow)
docker-compose up -d

# 2. Open Airflow UI
#    http://localhost:8088  (login: admin / admin)

# 3. Unpause the DAG and trigger manually, or wait for the daily schedule

# 4. (Recommended) Run producer + processor first so BigQuery has fresh data
python src/producer.py    # Terminal 1
python src/processor.py   # Terminal 2
```

**Note:** `clickstream-airflow-init` exits after startup — that is expected. It migrates the database, installs the Google provider, and creates the admin user once per `docker-compose up`.

### Service ports

| Service | URL / Port | Notes |
|---------|------------|-------|
| Airflow UI | http://localhost:8088 | Login: `admin` / `admin` |
| Kafka UI | http://localhost:8080 | Browse topics and messages |
| Flink UI | http://localhost:8081 | Infrastructure only; processor is Python |
| Kafka broker | `localhost:9092` | Used by producer/processor — **not** a browser URL |

---

## Resiliency Features

- **Dead-Letter Queue (DLQ):** Malformed records are written to timestamped files in `src/dlq_vault/` instead of crashing the pipeline. This keeps the stream running even when bad data arrives.

- **Idempotent upserts:** Each event is assigned a deterministic UUID generated from its content. If Kafka redelivers the same event, it updates the existing record rather than creating a duplicate.

- **Independent fork failure handling:** If one destination (ChromaDB or BigQuery) fails, the other still completes, and the failed write is logged to the DLQ. One store going down does not take down the other.

- **Batch writes with telemetry:** Events are buffered and flushed in small batches rather than one at a time, with latency and throughput logged on each flush.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Event ingestion | Apache Kafka (KRaft mode) |
| Stream processing | Python (confluent-kafka consumer) |
| AI vector store | ChromaDB |
| Cloud warehouse | Google BigQuery (free sandbox tier) |
| Containerization | Docker Compose |
| Orchestration | Apache Airflow 2.9 (LocalExecutor) |
| AI output | FastAPI + Anthropic Claude (optional) / mock LLM (default) |
| Monitoring UI | Kafka UI, Airflow UI |

---

## Requirements

Python dependencies for **local scripts** (producer, processor, and upcoming Phase 7 API) live in `requirements.txt`:

| Package | Used by |
|---------|---------|
| `confluent-kafka`, `faker` | Phase 1 — producer |
| `chromadb` | Phase 3 — ChromaDB upserts |
| `google-cloud-bigquery`, `google-auth` | Phase 5 — BigQuery fork |
| `anthropic`, `fastapi`, `uvicorn`, `pydantic`, `python-dotenv` | Phase 7 — LLM recommendation API |
| `apache-flink`, `dbt-bigquery` | Reserved for future Flink/dbt extensions |

**Airflow is not installed locally.** It runs inside the `apache/airflow:2.9.2-python3.11` Docker image. The Google BigQuery provider is installed at container startup via `_PIP_ADDITIONAL_REQUIREMENTS`.

**Phase 7 LLM cost:** Mock mode is free. Real Claude API calls bill separately from a Claude Pro chat subscription — see Phase 7 section below.

---

## Phase 7 — AI output layer (Recommendation API)

Phase 7 closes the loop: ChromaDB purchase vectors become **personalized recommendations** via a FastAPI service.

### Flow

1. Client sends `user_id` (+ optional question) to `POST /recommendations`.
2. API loads that user's purchases from ChromaDB (`realtime_user_contexts`).
3. API finds **similar shoppers' purchases** via vector search.
4. **Mock LLM** (default) or **Claude** generates recommendations from that context.

### Cost

| Mode | Cost | When to use |
|------|------|-------------|
| `USE_MOCK_LLM=true` (default) | **$0** | Development, demos, portfolio proof |
| `USE_MOCK_LLM=false` + `ANTHROPIC_API_KEY` | Pay-per-token (API) | Real AI output; use Haiku + few calls for pennies |

Claude Pro (chat subscription) does **not** replace the API key for this service.

### Setup

```bash
cp .env.example .env          # optional — mock mode works without .env
pip install -r requirements.txt
```

### Run (after producer + processor have filled ChromaDB)

```bash
# Terminal 3 — recommendation API
uvicorn src.recommendation_api:app --reload --port 8090
```

- Swagger UI: http://localhost:8090/docs
- Health: http://localhost:8090/health
- Debug context: `GET /users/{user_id}/context`
- Recommendations: `POST /recommendations` with body `{"user_id": 1234}`

### Enable real Claude (optional)

In `.env`:

```
USE_MOCK_LLM=false
ANTHROPIC_API_KEY=sk-ant-...
CLAUDE_MODEL=claude-3-haiku-20240307
```

Restart uvicorn. Each request sends one small API call.

### Verified Output

Successful recommendation from ChromaDB context via mock LLM (`POST /recommendations`, HTTP 200):

![Recommendation API success](./assets/recommendation_api_success.png)

---

## Quickstart

**1. Clone the repository and navigate into it.**

**2. Start the Docker infrastructure (Kafka, Flink, Airflow):**
```bash
docker-compose up -d
```

Airflow UI: http://localhost:8088 (login `admin` / `admin`). DAGs live in `dags/` and are paused on first load.

**3. Set up the Python environment:**
```bash
python -m venv .venv
.\.venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

**4. Add BigQuery credentials:**
Create a Google Cloud service account with BigQuery Data Editor and BigQuery Job User roles, download the JSON key, and save it as `src/gcp_credentials.json`. This file is gitignored and must never be committed. The same file is mounted into the Airflow container for DAG tasks.

**5. Run the pipeline (two terminals):**
```bash
# Terminal 1 — event generator
python src/producer.py

# Terminal 2 — processor
python src/processor.py
```

**6. Verify the output:**
- Kafka UI: http://localhost:8080
- Airflow: http://localhost:8088 — DAG `clickstream_pipeline_health`
- BigQuery: run `SELECT * FROM clickstream_analytics.purchase_events ORDER BY ingested_at DESC LIMIT 20` in the BigQuery console.

---

## Project Structure

```
realtime_clickstream_ai_engine/
├── dags/                          # Airflow DAG definitions (Phase 6)
│   └── clickstream_pipeline_health.py
├── logs/                          # Airflow runtime logs (gitignored)
├── src/
│   ├── producer.py                # Phase 1 — Kafka event generator
│   ├── processor.py               # Phases 2–5 — filter, validate, dual-fork
│   ├── recommendation_api.py    # Phase 7 — FastAPI + ChromaDB + LLM
│   ├── gcp_credentials.json       # GCP key (gitignored — you provide this)
│   ├── chroma_vault/              # ChromaDB data (gitignored)
│   └── dlq_vault/                 # Dead-letter files (gitignored)
├── .env.example                   # Phase 7 config template (copy to .env)
├── docker-compose.yml             # Kafka, Flink, Airflow, Postgres
├── requirements.txt               # Local Python dependencies
└── README.md
```

---

## Notes on Scale

This runs single-threaded on one machine, which is intentional for local development and debugging. In a production deployment, the processor would run with multiple Kafka partitions and parallel consumers, the warehouse writes would use streaming inserts instead of load jobs for lower latency, and producer/processor jobs would be containerized and scheduled entirely through Airflow rather than manual terminals.

---

## Roadmap

- [x] Phase 1 — Real-time ingestion (Python producer to Kafka)
- [x] Phase 2 — Stream processing (filter, validate, route)
- [x] Phase 3 — AI context storage (ChromaDB vector upserts)
- [x] Phase 4 — Resiliency (dead-letter queue, idempotent upserts, batch telemetry)
- [x] Phase 5 — Cloud warehouse (dual-fork to Google BigQuery)
- [x] Phase 6 — Orchestration (Apache Airflow for scheduling and monitoring)
- [x] Phase 7 — AI output layer (LLM reads ChromaDB to serve recommendations)
