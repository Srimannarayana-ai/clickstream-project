import json
import time
import random
import logging
import sys
from confluent_kafka import Producer
from faker import Faker

# Configure professional enterprise logging format
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] EnterpriseProducer: %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

fake = Faker()

conf = {
    'bootstrap.servers': 'localhost:9092',
    'client.id': 'enterprise-clickstream-producer',
    'acks': 'all',  # Guarantee highest durability barrier
    'retries': 5,
    'retry.backoff.ms': 500
}

def delivery_report(err, msg):
    if err is not None:
        logging.error(f"Event delivery failed structurally: {err}")
    else:
        # Trace exact topic offset mapping for telemetry audit
        pass

# Safe instantiation with recovery loop
producer = None
for attempt in range(1, 6):
    try:
        logging.info(f"Connecting to Kafka cluster broker (Attempt {attempt}/5)...")
        producer = Producer(conf)
        break
    except Exception as e:
        logging.warning(f"Broker unavailable. Linear backoff active: {e}")
        time.sleep(3)

if not producer:
    logging.critical("Failed to secure connection to Kafka. Halting execution.")
    sys.exit(1)

logging.info("Clickstream Producer active. Executing continuous simulation...")

try:
    while True:
        try:
            # Build clean metadata packet
            payload = {
                "user_id": random.randint(1000, 9999),
                "event_time": float(time.time()),
                "page_url": fake.uri(),
                "action": random.choice(["view", "click", "add_to_cart", "purchase"]),
                "platform": random.choice(["ios", "android", "web"])
            }
            
            # For technical interviews: Inject corrupt records occasionally to prove DLQ functionality
            if random.random() < 0.03:
                payload["user_id"] = "MALFORMED_STRING_DATA"

            serialized_data = json.dumps(payload).encode('utf-8')
            
            producer.produce(
                topic='clickstream',
                key=str(payload["user_id"]),
                value=serialized_data,
                callback=delivery_report
            )
            producer.poll(0)
            logging.info(f"Dispatched event payload: UID={payload['user_id']} | Action={payload['action']}")
            time.sleep(0.5)
            
        except BufferError:
            logging.warning("Kafka broker local buffer saturated. Activating pipeline throttle (1s delay)...")
            time.sleep(1.0)
        except Exception as e:
            logging.error(f"Transient trace processing error: {e}")

except KeyboardInterrupt:
    logging.info("Termination signal intercepted. Flushing local message queues...")
finally:
    producer.flush(timeout=5.0)
    logging.info("Producer pipeline fully disengaged.")