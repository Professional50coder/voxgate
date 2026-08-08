import importlib.util
import sys
from pathlib import Path
import yaml
from .base import Pack

class PackLoadError(Exception):
    """Exception raised when a pack fails to load, wrapping the underlying error with pack context."""
    pass

def _load_module(path: Path, qualname: str):
    spec = importlib.util.spec_from_file_location(qualname, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[qualname] = mod          # so pack modules can import each other
    spec.loader.exec_module(mod)
    return mod

def load_pack(path: Path) -> Pack:
    try:
        meta = yaml.safe_load((path / "pack.yaml").read_text(encoding="utf-8"))
        pid = meta["pack_id"]
        schema = _load_module(path / "schema.py", f"voxgate_pack_{pid}_schema")
        checks = _load_module(path / "checks.py", f"voxgate_pack_{pid}_checks")
        scoring = _load_module(path / "scoring.py", f"voxgate_pack_{pid}_scoring")
        low, high = meta["thresholds"]["low"], meta["thresholds"]["high"]
        return Pack(
            pack_id=pid, display_name=meta["display_name"], gate_role=meta["gate_role"],
            low_threshold=low, high_threshold=high,
            schema_model=schema.Schema, reask_hints=schema.REASK_HINTS,
            prompt=(path / "prompt.md").read_text(encoding="utf-8"),
            checks=checks.CHECKS, scorecard=scoring.build_scorecard(low, high),
            feature_field_hints=scoring.FEATURE_FIELD_HINTS, path=path)
    except Exception as e:
        raise PackLoadError(f"Failed to load pack from {path}: {e}") from e

def load_packs(packs_dir: Path) -> dict[str, Pack]:
    out: dict[str, Pack] = {}
    pack_paths: dict[str, Path] = {}  # track pack_id -> directory for collision detection
    for child in sorted(packs_dir.iterdir()):
        if child.is_dir() and (child / "pack.yaml").exists():
            pack = load_pack(child)
            if pack.pack_id in out:
                raise ValueError(
                    f"Duplicate pack_id '{pack.pack_id}' found in {pack_paths[pack.pack_id]} and {child}"
                )
            out[pack.pack_id] = pack
            pack_paths[pack.pack_id] = child
    return out
