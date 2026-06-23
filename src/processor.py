import os
import sys
import json
import uuid
import time
import logging
from datetime import datetime, timezone
from confluent_kafka import Consumer, TopicPartition, KafkaError, OFFSET_END
from confluent_kafka.admin import AdminClient, NewTopic

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] StreamProcessorEngine: %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

# ── Config ────────────────────────────────────────────────────────────────────
KAFKA_BOOTSTRAP = 'localhost:9092'
KAFKA_TOPIC     = 'clickstream'

GCP_CREDENTIALS = os.path.join(os.path.dirname(__file__), 'gcp_credentials.json')
BQ_PROJECT_ID   = 'clickstream-project-500108'
BQ_DATASET      = 'clickstream_analytics'
BQ_TABLE        = 'purchase_events'

BASE_DIR        = os.path.dirname(os.path.abspath(__file__))
CHROMA_DIR      = os.path.join(BASE_DIR, 'chroma_vault')
DLQ_DIR         = os.path.join(BASE_DIR, 'dlq_vault')

BATCH_SIZE      = 5
FLUSH_INTERVAL  = 2.0

# ── Ensure topic exists ───────────────────────────────────────────────────────
try:
    admin = AdminClient({'bootstrap.servers': KAFKA_BOOTSTRAP})
    meta  = admin.list_topics(timeout=5)
    if KAFKA_TOPIC not in meta.topics:
        fs = admin.create_topics([NewTopic(KAFKA_TOPIC, num_partitions=1, replication_factor=1)])
        for t, f in fs.items():
            f.result()
        logging.info(f'Created topic: {KAFKA_TOPIC}')
    else:
        logging.info(f'Topic exists: {KAFKA_TOPIC} | Partitions: {len(meta.topics[KAFKA_TOPIC].partitions)}')
except Exception as e:
    logging.error(f'Kafka admin error: {e}')

# ── Initialise sinks ──────────────────────────────────────────────────────────
import chromadb
chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
collection    = chroma_client.get_or_create_collection(name='realtime_user_contexts')
os.makedirs(DLQ_DIR, exist_ok=True)
logging.info(f'ChromaDB ready → {CHROMA_DIR}')

from google.cloud import bigquery
from google.oauth2 import service_account
credentials  = service_account.Credentials.from_service_account_file(
    GCP_CREDENTIALS, scopes=['https://www.googleapis.com/auth/bigquery']
)
bq_client    = bigquery.Client(project=BQ_PROJECT_ID, credentials=credentials)
bq_table_ref = f'{BQ_PROJECT_ID}.{BQ_DATASET}.{BQ_TABLE}'
logging.info(f'BigQuery ready → {bq_table_ref}')

# ── Kafka consumer — direct partition assignment (no group coordinator) ────────
def _on_error(err):
    logging.error(f'Kafka error callback: {err}')

consumer = Consumer({
    'bootstrap.servers':  KAFKA_BOOTSTRAP,
    'group.id':           'clickstream-direct-reader',
    'auto.offset.reset':  'latest',
    'enable.auto.commit': False,
    'error_cb':           _on_error,
})

# Assign partition 0 at OFFSET_END — reads only NEW messages from this point
# No group coordinator needed. No seek() needed. No erroneous state.
consumer.assign([TopicPartition(KAFKA_TOPIC, 0, OFFSET_END)])
logging.info(f'Kafka assigned → {KAFKA_TOPIC}[0] at OFFSET_END (latest)')

# ── Helpers ───────────────────────────────────────────────────────────────────
def route_to_dlq(payload, error):
    dlq_file = os.path.join(DLQ_DIR, f'dlq_{int(time.time())}.json')
    with open(dlq_file, 'a') as f:
        f.write(json.dumps({
            'processed_at': time.time(),
            'raw_payload':  str(payload),
            'error':        str(error)
        }) + '\n')

def flush_batch(batch):
    if not batch:
        return
    start      = time.time()
    chroma_ok  = False
    bq_ok      = False

    # FORK A — ChromaDB (AI vector layer) — runs independently
    try:
        collection.upsert(
            ids       = [r['id']       for r in batch],
            documents = [r['document'] for r in batch],
            metadatas = [r['metadata'] for r in batch]
        )
        chroma_ok = True
    except Exception as e:
        logging.error(f'ChromaDB flush error: {e}')
        for item in batch:
            route_to_dlq(item, f'ChromaDB error: {e}')

    # FORK B — BigQuery (analytics warehouse)
    # Uses load job instead of streaming insert — works with BigQuery sandbox free tier
    try:
        bq_rows = [r['bq_row'] for r in batch]
        job = bq_client.load_table_from_json(
            bq_rows,
            bq_table_ref,
            job_config=bigquery.LoadJobConfig(
                write_disposition='WRITE_APPEND',
                schema=[
                    bigquery.SchemaField('user_id',     'INTEGER'),
                    bigquery.SchemaField('event_time',  'FLOAT64'),
                    bigquery.SchemaField('page_url',    'STRING'),
                    bigquery.SchemaField('action',      'STRING'),
                    bigquery.SchemaField('platform',    'STRING'),
                    bigquery.SchemaField('ingested_at', 'TIMESTAMP'),
                ]
            )
        )
        job.result()  # Wait for load job to complete
        bq_ok = True
    except Exception as e:
        logging.error(f'BigQuery flush error: {e}')
        for item in batch:
            route_to_dlq(item, f'BigQuery error: {e}')

    ms = (time.time() - start) * 1000
    logging.info(
        f'[DUAL-FORK FLUSH] Rows: {len(batch)} | '
        f'ChromaDB {"✓" if chroma_ok else "✗"} | '
        f'BigQuery {"✓" if bq_ok else "✗"} | '
        f'Latency: {ms:.2f}ms'
    )

# ── Main stream loop ──────────────────────────────────────────────────────────
logging.info('Dual-Fork processor running. Listening for purchase events...')

batch          = []
last_flush     = time.time()
last_heartbeat = time.time()
poll_count     = 0
total_received = 0

try:
    while True:
        msg = consumer.poll(timeout=0.5)
        poll_count += 1

        if time.time() - last_flush >= FLUSH_INTERVAL:
            flush_batch(batch)
            batch      = []
            last_flush = time.time()

        if time.time() - last_heartbeat >= 10:
            logging.info(
                f'[HEARTBEAT] Polls: {poll_count} | '
                f'Messages received: {total_received} | '
                f'Batch queued: {len(batch)}'
            )
            last_heartbeat = time.time()

        if msg is None:
            continue

        if msg.error():
            code = msg.error().code()
            if code == KafkaError._PARTITION_EOF:
                logging.info(f'Reached end of partition at offset {msg.offset()}')
            else:
                logging.error(f'Kafka message error: {msg.error()}')
            continue

        total_received += 1

        try:
            event  = json.loads(msg.value().decode('utf-8'))
            action = event.get('action', '')

            logging.info(f'Received: UID={event.get("user_id")} | Action={action}')

            if action != 'purchase':
                continue

            user_id    = str(event.get('user_id', ''))
            event_time = float(event.get('event_time', time.time()))
            page_url   = str(event.get('page_url', ''))
            platform   = str(event.get('platform', ''))

            if not user_id.isdigit():
                raise ValueError(f"user_id '{user_id}' must be numeric")

            det_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f'{user_id}-{event_time}'))

            batch.append({
                'id':       det_id,
                'document': f'User {user_id} purchased on {platform} at {page_url}',
                'metadata': {'user_id': int(user_id), 'timestamp': event_time, 'platform': platform},
                'bq_row':   {
                    'user_id':    int(user_id),
                    'event_time': event_time,
                    'page_url':   page_url,
                    'action':     action,
                    'platform':   platform,
                    'ingested_at': datetime.now(timezone.utc).isoformat()
                }
            })

            logging.info(f'Queued purchase | UID={user_id} | Platform={platform}')

            if len(batch) >= BATCH_SIZE:
                flush_batch(batch)
                batch      = []
                last_flush = time.time()

        except Exception as e:
            route_to_dlq(msg.value(), str(e))
            logging.warning(f'Routed to DLQ: {e}')

except KeyboardInterrupt:
    logging.info('Shutdown signal. Flushing final batch...')
    flush_batch(batch)
finally:
    consumer.close()
    logging.info('Processor shut down cleanly.')