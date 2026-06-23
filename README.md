# Real-Time Clickstream & AI Context Pipeline

![Python](https://img.shields.io/badge/Python-3.11-blue.svg)
![Apache Kafka](https://img.shields.io/badge/Apache%20Kafka-KRaft-black.svg)
![BigQuery](https://img.shields.io/badge/Google%20BigQuery-Warehouse-4285F4.svg)
![ChromaDB](https://img.shields.io/badge/ChromaDB-Vector%20Store-FF4B4B.svg)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED.svg)

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
(events)    (queue)   (filter +      └─→  BigQuery   (cloud warehouse)
                       validate)
```

### Components

1. **Producer** (`src/producer.py`) — generates simulated clickstream events using the Faker library and publishes them to Kafka. It deliberately injects a small percentage of malformed records to test the pipeline's error handling.

2. **Kafka** — acts as the message queue between the producer and processor. It decouples the two, so if the processor slows down or restarts, events wait safely in the queue instead of being lost.

3. **Processor** (`src/processor.py`) — consumes events from Kafka, keeps only purchase events, validates them, then writes each valid event to both ChromaDB and BigQuery. Invalid records are routed to a dead-letter queue.

4. **ChromaDB** — stores each purchase as a vector embedding for AI-driven similarity search.

5. **BigQuery** — stores each purchase as a structured row in a cloud warehouse table for SQL analytics.

### Verified Output

Purchase events landing in the BigQuery warehouse table, queried with SQL:

![BigQuery purchase events](./assets/bigquery_output.png)

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
| Monitoring UI | Kafka UI |

---

## Quickstart

**1. Clone the repository and navigate into it.**

**2. Start the Docker infrastructure (Kafka + Kafka UI):**
```bash
docker-compose up -d
```

**3. Set up the Python environment:**
```bash
python -m venv .venv
.\.venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

**4. Add BigQuery credentials:**
Create a Google Cloud service account with BigQuery Data Editor and BigQuery Job User roles, download the JSON key, and save it as `src/gcp_credentials.json`. This file is gitignored and must never be committed.

**5. Run the pipeline (two terminals):**
```bash
# Terminal 1 — event generator
python src/producer.py

# Terminal 2 — processor
python src/processor.py
```

**6. Verify the output:**
- Kafka UI: http://localhost:8080
- BigQuery: run `SELECT * FROM clickstream_analytics.purchase_events ORDER BY ingested_at DESC LIMIT 20` in the BigQuery console.

---

## Notes on Scale

This runs single-threaded on one machine, which is intentional for local development and debugging. In a production deployment, the processor would run with multiple Kafka partitions and parallel consumers, the warehouse writes would use streaming inserts instead of load jobs for lower latency, and orchestration would be handled by a scheduler such as Apache Airflow.

---

## Roadmap

- [x] Phase 1 — Real-time ingestion (Python producer to Kafka)
- [x] Phase 2 — Stream processing (filter, validate, route)
- [x] Phase 3 — AI context storage (ChromaDB vector upserts)
- [x] Phase 4 — Resiliency (dead-letter queue, idempotent upserts, batch telemetry)
- [x] Phase 5 — Cloud warehouse (dual-fork to Google BigQuery)
- [ ] Phase 6 — Orchestration (Apache Airflow for scheduling and monitoring)
- [ ] Phase 7 — AI output layer (LLM reads ChromaDB to serve recommendations)