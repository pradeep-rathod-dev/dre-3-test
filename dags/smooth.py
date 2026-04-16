"""
dags/smooth.py

Bug fixes applied:
1. 'def smooth()' was missing a colon — Python syntax error, DAG failed to parse entirely
2. 'from airflow.operators.smooth import SmoothOperator' — SmoothOperator does not exist
   in the Airflow standard library. Moved to custom plugin at plugins/smooth_operator.py
"""

from airflow.decorators import dag
from smooth_operator import SmoothOperator  # loaded from /opt/airflow/plugins/
from datetime import datetime


@dag(
    schedule=None,
    start_date=datetime(2023, 1, 1),
    catchup=False,
    tags=["smooth"],
)
def smooth():  # FIX #1: missing colon on original 'def smooth()'
    video = SmoothOperator(
        task_id="youtube_video",
        message="Playing it smooth.",
    )


smooth()
