import json
import time
import random
from confluent_kafka import Producer
from faker import Faker

# 1. Initialize Faker to generate fake user data
fake = Faker()

# 2. Kafka Configuration
# 'bootstrap.servers' tells Python where to find the post office (Kafka)
# Since Python is running on Windows, we use localhost:9092
conf = {
    'bootstrap.servers': 'localhost:9092',
    'client.id': 'python-clickstream-producer'
}

# 3. Create the Producer instance
producer = Producer(conf)

# This helper function tells us if the message was sent successfully
def delivery_report(err, msg):
    if err is not None:
        print(f"Message delivery failed: {err}")
    else:
        print(f"Message delivered to {msg.topic()} [{msg.partition()}]")

print("Starting Clickstream Producer... Press Ctrl+C to stop.")

try:
    while True:
        # 4. Create a fake "Click" event
        data = {
            "user_id": random.randint(1000, 9999),
            "event_time": time.time(),
            "page_url": fake.uri(),
            "action": random.choice(["view", "click", "add_to_cart", "purchase"]),
            "platform": random.choice(["ios", "android", "web"])
        }

        # 5. Send data to the 'clickstream' topic
        # We must 'encode' the dictionary into a JSON string
        producer.produce(
            topic='clickstream', 
            key=str(data["user_id"]), 
            value=json.dumps(data).encode('utf-8'),
            callback=delivery_report
        )

        # 6. Flush tells Kafka to send the message NOW
        producer.poll(0)
        
        # Wait 1 second before sending the next click
        time.sleep(1)

except KeyboardInterrupt:
    print("\nStopping producer...")
finally:
    # 7. Clean up and ensure all messages are sent before closing
    producer.flush()