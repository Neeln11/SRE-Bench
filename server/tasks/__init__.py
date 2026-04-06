"""
tasks/__init__.py — Task registry for SRE-Bench.
Maps task_id strings to their environment classes.
"""

from tasks.task_disk_full import DiskFullEnv
from tasks.task_db_pool import DBPoolEnv
from tasks.task_data_corruption import DataCorruptionEnv

TASK_REGISTRY = {
    "disk_full":         DiskFullEnv,
    "db_pool_exhausted": DBPoolEnv,
    "data_corruption":   DataCorruptionEnv,
}

__all__ = ["TASK_REGISTRY"]
