"""
Plugins/smooth_operator.py

SmoothOperator is not part of the standard Airflow library.
This plugin implements it as a custom BaseOperator so the DAG can run.

The operator logs a message and sleeps briefly to simulate
a smooth, non-blocking task - consistent with the DAG's intent.
"""

import time
import logging

from airflow.models.baseoperator import BaseOperator
from airflow.utils.decorators import apply_defaults

log = logging.getLogger(__name__)


class SmoothOperator(BaseOperator):
    """
    A custom Airflow operator that executes smoothly.

    This operator was missing from the standard Airflow distribution.
    It performs a configurable sleep to simulate a smooth background task,
    then logs completion. Suitable as a placeholder or lightweight task node.

    :param sleep_seconds: How long to sleep (default: 2 seconds)
    :param message: Optional custom log message
    """

    ui_color = "#f0e68c"  # light yellow in the Airflow task graph

    @apply_defaults
    def __init__(
        self,
        sleep_seconds: int = 2,
        message: str = "Running smooth...",
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.sleep_seconds = sleep_seconds
        self.message = message

    def execute(self, context):
        log.info("SmoothOperator starting: %s", self.message)
        log.info("Task run date: %s", context["ds"])
        time.sleep(self.sleep_seconds)
        log.info("SmoothOperator completed successfully after %ss", self.sleep_seconds)
        return {"status": "smooth", "duration_seconds": self.sleep_seconds}