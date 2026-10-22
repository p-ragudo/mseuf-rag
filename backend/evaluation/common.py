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


def infer_domain_cluster(url: str = "", heading: str = "", text: str = "") -> str:
    """Classifies a chunk/record into one of three balanced domain clusters:
    - faqs_procedures: Admissions procedures, step-by-step application/enrollment guides, FAQs
    - policies_announcements: Institutional announcements, suspensions, holidays, dress code, quality objectives, vision/mission
    - specs_programs: Academic programs, curricula, facilities/studios, faculty/deans, research/awards, job specs
    """
    u = (url or "").lower()
    h = (heading or "").lower()
    t = (text or "").lower()[:400]

    if "frequently-asked-questions" in u or "/admission" in u or "admission" in h or "procedure" in h:
        return "faqs_procedures"
    if any(k in u for k in ("/announcements/", "memorandum", "dress-code", "quality-objectives", "vision-mission", "philosophy")):
        return "policies_announcements"
    if any(k in h for k in ("announcement", "no classes", "no office", "dress code", "quality objectives", "vision", "mission", "philosophy", "reminders for graduates")):
        return "policies_announcements"
    if "step 1" in t or "1. the applicant" in t:
        return "faqs_procedures"
    return "specs_programs"


def normalize_record(raw: Dict[str, Any], use_blind_query: bool = False) -> Dict[str, Any]:
    """Normalizes synthetic_100, faqs_21, real_user_71, and legacy v1/v2 schemas."""
    r = dict(raw)
    ids = [int(x) for x in (r.get("ground_truth_chunk_ids") or []) if x is not None]
    req_ids = [int(x) for x in (r.get("required_chunk_ids") or ids) if x is not None]

    r["ground_truth_chunk_ids"] = ids
    r["required_chunk_ids"] = req_ids
    r.setdefault("set_name", "synthetic_100")
    r.setdefault("answerable", r.get("set_name") != "negative")
    r.setdefault(
        "has_ground_truth",
        bool(r.get("ground_truth_answer") or ids or r.get("ground_truth_contexts")),
    )
    r.setdefault("primary_chunk_id", req_ids[0] if req_ids else (ids[0] if ids else None))
    r.setdefault("ground_truth_answer", None)
    r["ground_truth_contexts"] = r.get("ground_truth_contexts") or []
    r.setdefault("source_url", None)
    r.setdefault("heading_path", "")

    first_ctx = r["ground_truth_contexts"][0] if r["ground_truth_contexts"] else ""
    r.setdefault(
        "domain_cluster",
        infer_domain_cluster(r.get("source_url") or "", r.get("heading_path") or "", first_ctx),
    )
    r.setdefault(
        "difficulty",
        "easy" if len(req_ids) <= 1 else ("medium" if len(req_ids) == 2 else "hard"),
    )

    base_q = (r.get("base_user_query") or r.get("user_query") or "").strip()
    blind_q = (r.get("blind_user_query") or "").strip()
    r["base_user_query"] = base_q
    r["blind_user_query"] = blind_q or None

    if use_blind_query and blind_q:
        r["user_query"] = blind_q
        r["active_query_mode"] = "blind"
    else:
        r["user_query"] = r.get("user_query", base_q).strip()
        r["active_query_mode"] = "blind" if (r.get("query_mode") == "blind") else "base"

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