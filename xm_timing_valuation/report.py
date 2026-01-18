import csv
import logging
import os
from typing import Dict, List

logger = logging.getLogger(__name__)


def ensure_csv_header(path: str, fieldnames: List[str]) -> None:
    if os.path.exists(path):
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()


def append_csv(path: str, fieldnames: List[str], row: Dict[str, object]) -> None:
    ensure_csv_header(path, fieldnames)
    with open(path, "a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writerow(row)


def print_console(summary_lines: List[str]) -> None:
    for line in summary_lines:
        logger.info(line)
