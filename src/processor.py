import os
import sys
import json
import uuid
import time
import logging
from pathlib import Path
from pyflink.datastream import StreamExecutionEnvironment
from pyflink.table import EnvironmentSettings, StreamTableEnvironment
from pyflink.common import Configuration
from pyflink.common.typeinfo import Types
from pyflink.datastream.functions import FlatMapFunction

# Configure localized operational logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] StreamProcessorEngine: %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

# --- DEPENDENCY SETUP ---
KAFKA_JAR_URL = "https://repo.maven.apache.org/maven2/org/apache/flink/flink-sql-connector-kafka/1.18.1/flink-sql-connector-kafka-1.18.1.jar"
JAR_DIR = os.path.join(os.path.dirname(__file__))
KAFKA_JAR_PATH = os.path.join(JAR_DIR, "flink-sql-connector-kafka.jar")

if not os.path.exists(KAFKA_JAR_PATH):
    import urllib.request
    logging.info("Fetching Flink SQL Kafka connector library jar...")
    urllib.request.urlretrieve(KAFKA_JAR_URL, KAFKA_JAR_PATH)

jar_paths = f"{Path(KAFKA_JAR_PATH).as_uri()}"
os.environ.setdefault("PIPELINE_JARS", jar_paths)

# 1. Start the Flink Streaming Environment
config = Configuration()
config.set_string("rest.address", "localhost")
config.set_string("rest.port", "8083")
config.set_string("pipeline.jars", jar_paths)
config.set_string("python.files", __file__)
config.set_string("python.execution-mode", "LOOPBACK")
config.set_string("python.client.executable", sys.executable)

logging.info("Compiling stream topology locally and dispatching graph to active Docker cluster at localhost:8081...")
env = StreamExecutionEnvironment.get_execution_environment(config)

# LOCAL DEVELOPMENT ALIGNMENT
# Explicitly locking parallelism to 1 for localized state debugging and sequential log auditing.
env.set_parallelism(1)

# Disable chaining so the DAG renders fully unpacked in the Flink Web UI for visual demonstrations
env.disable_operator_chaining()

env_settings = EnvironmentSettings.new_instance().in_streaming_mode().build()
t_env = StreamTableEnvironment.create(env, environment_settings=env_settings)

# 2. Define the Kafka Ingestion Topologies
t_env.execute_sql("""
    CREATE TABLE clickstream_source (
        user_id STRING,
        event_time DOUBLE,
        page_url STRING,
        action STRING,
        platform STRING
    ) WITH (
        'connector' = 'kafka',
        'topic' = 'clickstream',
        'properties.bootstrap.servers' = 'localhost:9092',
        'properties.group.id' = 'enterprise-flink-group',
        'format' = 'json',
        'scan.startup.mode' = 'latest-offset'
    )
""")

purchase_table = t_env.sql_query("""
    SELECT user_id, event_time, page_url, action, platform 
    FROM clickstream_source 
    WHERE action = 'purchase'
""")

data_stream = t_env.to_data_stream(purchase_table)

# --- ENTERPRISE VECTOR SINK LAYER (FLATMAP IMPLEMENTATION) ---
class EnterpriseChromaVectorSink(FlatMapFunction):
    def __init__(self, storage_path, dlq_path):
        self.storage_path = storage_path
        self.dlq_path = dlq_path
        self.chroma_client = None
        self.collection = None
        self.batch_buffer = []
        self.max_batch_size = 5
        self.last_flush_time = time.time()
        
    def open(self, runtime_context):
        import chromadb
        self.chroma_client = chromadb.PersistentClient(path=self.storage_path)
        self.collection = self.chroma_client.get_or_create_collection(name="realtime_user_contexts")
        os.makedirs(self.dlq_path, exist_ok=True)
        logging.info(f"Vector Database Abstraction Engine initialized successfully at path: {self.storage_path}")

    def flat_map(self, value):
        try:
            user_id = str(value[0])
            event_time = float(value[1])
            page_url = str(value[2])
            action = str(value[3])
            platform = str(value[4])
            
            if not user_id.isdigit():
                raise ValueError(f"Schema violation constraint matched. user_id '{user_id}' must map cleanly to an INT type identifier.")
                
            deterministic_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{user_id}-{event_time}"))
            vector_document = f"User {user_id} executed a {action} transaction event on the {platform} network channel targeting URL: {page_url}"
            
            record_metadata = {
                "user_id": int(user_id),
                "timestamp": event_time,
                "platform": platform
            }
            
            self.batch_buffer.append({
                "id": deterministic_id,
                "document": vector_document,
                "metadata": record_metadata
            })
            
            if len(self.batch_buffer) >= self.max_batch_size or (time.time() - self.last_flush_time) > 2.0:
                self.flush_batch()
                
        except Exception as err:
            self.route_to_dlq(value, str(err))
            yield str(f"FAILURE: {err}")
            
    def flush_batch(self):
        if not self.batch_buffer:
            return
            
        start_flush = time.time()
        try:
            ids = [item["id"] for item in self.batch_buffer]
            documents = [item["document"] for item in self.batch_buffer]
            metadatas = [item["metadata"] for item in self.batch_buffer]
            
            self.collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas
            )
            
            end_flush = time.time()
            latency_ms = (end_flush - start_flush) * 1000
            throughput = len(self.batch_buffer) / (end_flush - start_flush + 0.0001)
            
            logging.info(
                f"[PRODUCTION TELEMETRY] Batch Flush Complete | Size: {len(self.batch_buffer)} rows | "
                f"Storage Sync Latency: {latency_ms:.2f}ms | Throughput Rate: {throughput:.1f} events/sec"
            )
            
            self.batch_buffer.clear()
            self.last_flush_time = time.time()
            
        except Exception as e:
            logging.error(f"Transient error encountered during vector store serialization write back: {e}")
            for failed_item in self.batch_buffer:
                self.route_to_dlq(failed_item, f"Batch Flush Write Failure: {str(e)}")
            self.batch_buffer.clear()

    def route_to_dlq(self, payload, error_message):
        dlq_file = os.path.join(self.dlq_path, f"dlq_failures_{int(time.time())}.json")
        failure_packet = {
            "processed_at": time.time(),
            "raw_payload": str(payload),
            "root_cause_exception": error_message
        }
        with open(dlq_file, 'a') as df:
            df.write(json.dumps(failure_packet) + "\n")

    def close(self):
        self.flush_batch()


base_dir = os.path.dirname(os.path.abspath(__file__))
chroma_storage_dir = os.path.join(base_dir, "chroma_vault")
dlq_storage_dir = os.path.join(base_dir, "dlq_vault")

# THE FIX: Explicitly rename the execution nodes so the Flink Web UI renders accurate architectural descriptions
processed_stream = data_stream.flat_map(
    EnterpriseChromaVectorSink(chroma_storage_dir, dlq_storage_dir),
    output_type=Types.STRING()
).name("Vector Processing: ChromaDB Upsert & DLQ Router")

# Final execution node acts solely as a diagnostic sink for yielded DLQ warnings
processed_stream.print().name("Sink: Diagnostic Terminal Output")

logging.info("Deploying execution plan DAG payload to remote Flink JobManager...")
env.execute("Enterprise Real-Time Clickstream Vector Storage Framework")