"""Small shared helpers (no app imports, safe to unit-test offline)."""
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

EVAL_DIR = Path(__file__).resolve().parent

# Common Tagalog function words / particles used to detect Tagalog or Taglish responses
_TAGALOG_MARKERS = frozenset({
    "ang", "mga", "ng", "sa", "na", "at", "ay", "po", "opo", "hindi", "kung",
    "para", "ito", "iyan", "iyon", "kayo", "kami", "tayo", "sila", "niya",
    "nila", "inyo", "atin", "amin", "kailangan", "pwede", "puwede", "maaari",
    "paano", "saan", "kailan", "bakit", "ano", "sino", "alin", "magkano",
    "dahil", "kapag", "upang", "mula", "hanggang", "bilang", "bawat", "lahat",
    "lamang", "lang", "din", "rin", "daw", "raw", "ba", "pa", "na", "naman",
    "muna", "pala", "kaya", "tulad", "ayon", "tungkol", "kaugnay", "hakbang",
    "dokumento", "aplikante", "estudyante", "mag-aaral", "paaralan", "unibersidad",
})


def is_english_text(text: str, max_tagalog_ratio: float = 0.03) -> bool:
    """Returns True if `text` is written in English (and not Tagalog or Taglish).

    Used to gate traditional lexical metrics (BLEU, ROUGE, Token F1) so they are
    only computed when the generated answer is in English, matching the English
    ground-truth reference.
    """
    words = re.findall(r"[a-zA-ZÀ-ÿ]+(?:-[a-zA-ZÀ-ÿ]+)?", (text or "").lower())
    if not words:
        return False
    tagalog_hits = sum(1 for w in words if w in _TAGALOG_MARKERS)
    if tagalog_hits >= 3 or (tagalog_hits / len(words)) > max_tagalog_ratio:
        return False
    return True


def detect_query_language(text: str) -> str:
    """Heuristic fallback if a record does not have an explicit `language` field."""
    words = re.findall(r"[a-zA-ZÀ-ÿ]+(?:-[a-zA-ZÀ-ÿ]+)?", (text or "").lower())
    if not words:
        return "English"
    tagalog_hits = sum(1 for w in words if w in _TAGALOG_MARKERS)
    ratio = tagalog_hits / len(words)
    if tagalog_hits == 0:
        return "English"
    if ratio >= 0.35:
        return "Tagalog"
    return "Taglish"


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
    """Normalizes synthetic_150, faqs_63, real_user_71, and legacy v1/v2 schemas."""
    r = dict(raw)
    ids = [int(x) for x in (r.get("ground_truth_chunk_ids") or []) if x is not None]
    req_ids = [int(x) for x in (r.get("required_chunk_ids") or ids) if x is not None]

    r["ground_truth_chunk_ids"] = ids
    r["required_chunk_ids"] = req_ids
    r.setdefault("set_name", "synthetic_150")
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
        r["user_query"] = (r.get("user_query") or base_q).strip()
        r["active_query_mode"] = "blind" if (r.get("query_mode") == "blind") else "base"

    # Preserve explicit language ("English", "Tagalog", "Taglish") or infer from query text
    explicit_lang = r.get("language") or r.get("language_constraint")
    if explicit_lang in ("English", "Tagalog", "Taglish"):
        r["language"] = explicit_lang
    else:
        r["language"] = detect_query_language(r["user_query"])

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