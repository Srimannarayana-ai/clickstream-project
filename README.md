# Real-Time Clickstream & AI Context Engine

## Version 1: The Ingestion Pipeline
This project simulates real-time e-commerce traffic using Python and streams it into an Apache Kafka cluster running in Docker.

### Tech Stack
* **Language:** Python 3.12+
* **Stream Platform:** Apache Kafka (KRaft mode)
* **Infrastructure:** Docker Desktop
* **Libraries:** `confluent-kafka`, `faker`

### How to Run
1. Start the infrastructure: `docker-compose up -d`
2. Activate the environment: `.\.venv\Scripts\activate`
3. Run the producer: `python src/producer.py`