# Real-Time Clickstream & AI Context Engine

## 📖 Project Overview
This project simulates the foundational infrastructure of a modern e-commerce data platform. It captures high-volume user interaction data (clickstreams) in real-time, providing the reliable "nervous system" required for downstream stream-processing and AI-driven personalization.

### 🏗️ Current Architecture (Version 1: Ingestion)
Currently, the pipeline consists of a Python-based data generator acting as the web client, streaming JSON payloads directly into a localized Apache Kafka cluster running in KRaft mode.

* **Data Generator:** Python (`faker`, `confluent-kafka`)
* **Message Broker:** Apache Kafka 
* **Containerization:** Docker Desktop
* **Monitoring:** Kafka UI

## 📊 Data Schema (The Clickstream Event)
Data is streamed to the `clickstream` topic in JSON format("Navigate to Topics-->Clickstream-->Messeges"). Here is an example of a single event:

```json
{
  "user_id": 4124,
  "event_time": 1713292405.123,
  "page_url": "[https://www.example.com/category/shoes](https://www.example.com/category/shoes)",
  "action": "add_to_cart",
  "platform": "ios"
}

🚀 How to Run Locally

### Prerequisites:
* Windows 10/11
* Docker Desktop installed and running
* Python 3.12+

### Step-by-Step Setup
Start the Infrastructure:
1. Start the infrastructure: docker-compose up -d

2.Access the Monitoring UI:
Open a browser and navigate to http://localhost:8080

3. Activate the environment: .\.venv\Scripts\activate

4. pip install -r requirements.txt  # If requirements file exists

5. Run the producer: python src/producer.pyPowerShell


🗺️ Project Roadmap
[x] Phase 1: Real-Time Data Ingestion (Kafka + Python)

[ ] Phase 2: Stream Processing (Apache Flink)

[ ] Phase 3: AI Context Storage (PostgreSQL + pgvector) 