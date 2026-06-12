import json
import csv
from pathlib import Path


def export_json(rows, path):
    """Stream rows to path as JSON array."""
    Path(path).write_text(json.dumps(list(rows)))


def export_csv(rows, path):
    """Stream rows to path as RFC-4180 CSV with header row.

    Handles commas and quotes in cell values via RFC-4180 quoting rules.

    Args:
        rows: iterable of dicts with consistent keys (each row is a dict)
        path: destination file path
    """
    with open(path, 'w', newline='') as f:
        writer = None
        for row in rows:
            if writer is None:
                fieldnames = list(row.keys())
                writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL)
                writer.writeheader()
            writer.writerow(row)

        if writer is None:
            f.write("")
