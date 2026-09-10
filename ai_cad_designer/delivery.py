"""Portable, hash-indexed delivery archives for a single design run."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any


def build_delivery_bundle(root: str | Path, files: list[str]) -> dict[str, Any]:
    """Archive only current-run files and describe exactly what was packaged."""
    root_path = Path(root).resolve()
    entries: list[dict[str, str]] = []
    for value in files:
        path = Path(value).resolve()
        if path.is_file() and root_path in path.parents:
            entries.append({
                "path": str(path.relative_to(root_path)),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            })
    entries = sorted({item["path"]: item for item in entries}.values(), key=lambda item: item["path"])
    archive = root_path / "partpilot_delivery.zip"
    manifest = {"schema_version": 1, "artifact_count": len(entries), "artifacts": entries}
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for item in entries:
            bundle.write(root_path / item["path"], item["path"])
        bundle.writestr("delivery_manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
    return {"status": "passed", "archive": str(archive.resolve()), "manifest": manifest}
