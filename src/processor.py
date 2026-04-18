import os
import urllib.request
from pyflink.table import EnvironmentSettings, TableEnvironment
from pathlib import Path
from pyflink.common import Configuration

# 1. Download the Kafka-Flink Translator (Connector JAR) automatically
JAR_URL = "https://repo.maven.apache.org/maven2/org/apache/flink/flink-sql-connector-kafka/3.0.2-1.18/flink-sql-connector-kafka-3.0.2-1.18.jar"
JAR_PATH = os.path.join(os.path.dirname(__file__), "flink-sql-connector-kafka.jar")

if not os.path.exists(JAR_PATH):
    print("Downloading Kafka Connector JAR... (This only happens once)")
    urllib.request.urlretrieve(JAR_URL, JAR_PATH)

# 2. Start the Flink Environment (The Python MiniCluster)
# We configure it to expose a Web UI on port 8082 (so it doesn't fight Docker on 8081)
config = Configuration()
config.set_string("rest.port", "8082")
env_settings = EnvironmentSettings.new_instance().in_streaming_mode().with_configuration(config).build()
t_env = TableEnvironment.create(env_settings)
# Give Flink the translator we just downloaded
t_env.get_config().set("pipeline.jars", Path(JAR_PATH).as_uri())

# 3. Define the SOURCE (Where is the data coming from?)
# We use Flink SQL to make a "virtual table" over our Kafka topic
source_ddl = """
    CREATE TABLE clickstream_source (
        user_id INT,
        event_time DOUBLE,
        page_url STRING,
        action STRING,
        platform STRING
    ) WITH (
        'connector' = 'kafka',
        'topic' = 'clickstream',
        'properties.bootstrap.servers' = 'localhost:9092',
        'properties.group.id' = 'flink-processor-group',
        'scan.startup.mode' = 'latest-offset',
        'format' = 'json'
    )
"""
t_env.execute_sql(source_ddl)

# 4. Define the SINK (Where should the processed data go?)
# For now, we just want Flink to print it to our terminal console
sink_ddl = """
    CREATE TABLE print_sink (
        user_id INT,
        action STRING,
        platform STRING
    ) WITH (
        'connector' = 'print'
    )
"""
t_env.execute_sql(sink_ddl)

# 5. THE ENGINE LOGIC (Filtering the stream in real-time)
print("Starting Flink Job: Waiting for 'purchase' events...")

# We tell Flink to select ONLY rows where the action is 'purchase'
t_env.execute_sql("""
    INSERT INTO print_sink
    SELECT user_id, action, platform
    FROM clickstream_source
    WHERE action = 'purchase'
""").wait()