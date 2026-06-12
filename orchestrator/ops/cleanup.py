import os
from pathlib import Path

ARTIFACT_DIR = "/var/lib/app/artifacts"


def cleanup_artifact(name):
    """Delete the named artifact (name comes from the web API).

    Safely handles web-supplied names by validating path containment
    and using safe file deletion APIs.
    """
    if not name or not isinstance(name, str):
        raise ValueError("Invalid artifact name")

    # Reject path traversal attempts
    if ".." in name or name.startswith("/"):
        raise ValueError(f"Invalid artifact name: {name}")

    # Reject absolute paths and null bytes
    if "/" in name or "\\" in name or "\x00" in name:
        raise ValueError(f"Invalid artifact name: {name}")

    # Resolve the full path and verify it's within ARTIFACT_DIR
    artifact_path = Path(ARTIFACT_DIR) / name
    resolved_artifact = artifact_path.resolve()
    resolved_dir = Path(ARTIFACT_DIR).resolve()

    try:
        # Ensure the resolved path is within ARTIFACT_DIR
        resolved_artifact.relative_to(resolved_dir)
    except ValueError:
        raise ValueError(f"Path traversal attempt detected: {name}")

    # Delete the file if it exists
    if resolved_artifact.exists():
        resolved_artifact.unlink()

    return True
