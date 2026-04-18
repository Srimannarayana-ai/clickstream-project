# Real-Time Clickstream & AI Context Engine

## 📖 Project Overview
This project simulates the foundational infrastructure of a modern e-commerce data platform. It captures high-volume user interaction data (clickstreams) in real-time, providing the reliable "nervous system" required for downstream stream-processing and AI-driven personalization.

### 🏗️ Current Architecture (Version 2: Stream Processing)
The pipeline ingests raw JSON events into Apache Kafka and processes them in real-time using Apache Flink. Flink acts as the compute engine, aggressively filtering the firehose of clicks to isolate high-value business events (purchases) with sub-second latency.

* **Data Generator:** Python (`faker`, `confluent-kafka`)
* **Message Broker:** Apache Kafka (KRaft mode)
* **Stream Processing Engine:** Apache Flink (PyFlink 1.18)
* **Containerization:** Docker Desktop
* **Monitoring:** Kafka UI & Flink Web Dashboard

## 📊 Data Schema (The Clickstream Event)
Data is streamed to the `clickstream` topic in JSON format. Here is an example of a single event:

```json
{
  "user_id": 4124,
  "event_time": 1713292405.123,
  "page_url": "[https://www.example.com/category/shoes](https://www.example.com/category/shoes)",
  "action": "add_to_cart",
  "platform": "ios"
} 

```

# 🚀 How to Run Locally

## Prerequisites
* Windows 10/11
* Docker Desktop installed and running
* Python 3.11.x (Strictly required for PyFlink compatibility)
* Java 11 (Required for Flink local execution)

### Step-by-Step Setup

# Start the Infrastructure
# **PowerShell:**
* docker-compose up -d

## Access the Monitoring UIs
* **Kafka UI:** http://localhost:8080
* **Flink MiniCluster UI:** http://localhost:8082 (Available while processor is running)

## Run the Real-Time Pipeline (Requires 2 Terminals)
# **Terminal 1 (The Data Generator):**
**PowerShell:**
* .\.venv\Scripts\activate
* pip install confluent-kafka faker apache-flink==1.18.1 setuptools==69.5.1
* python src/producer.py

# **Terminal 2 (The Flink Engine):**

# **PowerShell:**
* .\.venv\Scripts\activate
* python src/processor.py

### 🗺️ Project Roadmap
[x] Phase 1: Real-Time Data Ingestion (Kafka + Python)

[x] Phase 2: Stream Processing (Apache Flink)

[ ] Phase 3: AI Context Storage (PostgreSQL + pgvector)