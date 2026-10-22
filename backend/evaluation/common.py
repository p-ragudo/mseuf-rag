"""Small shared helpers (no app imports, safe to unit-test offline)."""
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

EVAL_DIR = Path(__file__).resolve().parent


def normalize_ws(text: str) -> str:
    return " ".join((text or "").lower().split())


def content_sha(text: str) -> str:
    return hashlib.sha1(normalize_ws(text).encode("utf-8")).hexdigest()


def tenant_dir(org_id: int, create: bool = False) -> Path:
    d = EVAL_DIR / "data" / f"org_{org_id}"
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def write_jsonl(path: Path, records: Iterable[Dict[str, Any]]) -> int:
    n = 0
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    return n


def normalize_record(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Accepts both the old (v1) ground_truth.jsonl schema and the new one."""
    r = dict(raw)
    ids = [int(x) for x in (r.get("ground_truth_chunk_ids") or []) if x is not None]
    r["ground_truth_chunk_ids"] = ids
    r.setdefault("set_name", "synthetic_standard")
    r.setdefault("answerable", True)
    r.setdefault("primary_chunk_id", ids[0] if ids else None)
    r.setdefault("ground_truth_answer", None)
    r["ground_truth_contexts"] = r.get("ground_truth_contexts") or []
    r.setdefault("source_url", None)
    if not r.get("ground_truth_content_sha") and r["ground_truth_contexts"]:
        r["ground_truth_content_sha"] = content_sha(r["ground_truth_contexts"][0])
    return r


def load_dataset_meta(path: Path) -> Optional[Dict[str, Any]]:
    """<name>.meta.json (new) or metadata.json (old) next to the dataset file."""
    for cand in (path.with_suffix(".meta.json"), path.parent / "metadata.json"):
        if cand.exists():
            try:
                return json.loads(cand.read_text(encoding="utf-8"))
            except Exception:
                return None
    return None
