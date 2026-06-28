"""
Daily BigQuery warehouse health check for the clickstream pipeline.

Tasks:
  1. verify_warehouse_table — confirm purchase_events is reachable
  2. summarize_recent_purchases — count and freshness for the last 24 hours
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.providers.google.cloud.operators.bigquery import (
    BigQueryCheckOperator,
    BigQueryInsertJobOperator,
)

BQ_PROJECT = "clickstream-project-500108"
BQ_DATASET = "clickstream_analytics"
BQ_TABLE = "purchase_events"
BQ_TABLE_REF = f"{BQ_PROJECT}.{BQ_DATASET}.{BQ_TABLE}"
GCP_CONN_ID = "google_cloud_default"

default_args = {
    "owner": "clickstream",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="clickstream_pipeline_health",
    default_args=default_args,
    description="Daily BigQuery warehouse health check for clickstream purchases",
    schedule_interval="@daily",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["clickstream", "phase6", "bigquery", "orchestration"],
) as dag:
    verify_warehouse_table = BigQueryCheckOperator(
        task_id="verify_warehouse_table",
        sql=f"SELECT COUNT(*) >= 0 FROM `{BQ_TABLE_REF}`",
        use_legacy_sql=False,
        gcp_conn_id=GCP_CONN_ID,
        location="US",
    )

    summarize_recent_purchases = BigQueryInsertJobOperator(
        task_id="summarize_recent_purchases",
        gcp_conn_id=GCP_CONN_ID,
        project_id=BQ_PROJECT,
        configuration={
            "query": {
                "query": f"""
                    SELECT
                        COUNT(*) AS purchase_count,
                        MAX(ingested_at) AS latest_ingested_at
                    FROM `{BQ_TABLE_REF}`
                    WHERE ingested_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
                """,
                "useLegacySql": False,
            }
        },
        location="US",
    )

    verify_warehouse_table >> summarize_recent_purchases
