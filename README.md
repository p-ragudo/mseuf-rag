# Setup

## Backend Setup

Use **uv** instead of pip

---

### Prerequisites

* **Python 3.12+**
* **`uv`** (Package installer and environment manager)

If you do not have `uv` installed, run this in PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm [https://astral.sh/uv/install.ps1](https://astral.sh/uv/install.ps1) | iex"

or

pip install uv
```

then restart your terminal after running the installer

### Create a virtual environment and syncing packages

- Make sure your terminal is at **``backend/``** directory
- Create a virtual environment and sync packages
```powershell
## first run
uv venv

## activate the venv
.venv\Scripts\activate

## then run
uv pip sync requirements.txt
```
## Svelte Setup

### Prerequisites

Have **`npm`** installed

### Install packages

- Make sure your terminal is at **``frontend/``** directory
```powershell
npm install
```

## Installing Packages for Python

Whenever your project's dependencies change, follow these three steps:

1. Edit requirements.in (by hand)

2. Update the lockfile
```
uv pip compile requirements.in --universal -o requirements.txt
```

3. Apply changes to your local .venv
```
uv pip sync requirements.txt
```

## Install playwright first (if you don't have it yet) before running the app:
Make sure you are in the backend directory
```
uv run playwright install --with-deps chromium
```

## To run the backend, run:
```
uv run uvicorn app.main:app --reload --reload-dir app
```
or
```
uv run fastapi run app/main.py
```

## Stopping background processes in the backend
When you stop the fastapi application, it may not always stop the other background processes.

(this is on linux)
```bash
pkill -9 -f "python" || true
pkill -9 -f "uvicorn" || true
pkill -9 -f "telegram_bot" || true
```

## Environment variables to watch out for
```bash
# ==============================================================================
# Production & Base Environments
# ==============================================================================
DATABASE_URL=value
SEMANTIC_CACHE_INDEX_NAME=value
COLLECTION_NAME=value
TELEGRAM_BOT_TOKEN=value
TELEGRAM_BOT_FASTAPI_KEY=value

# ==============================================================================
# Test / Non-Prod Environments
# ==============================================================================
DATABASE_URL_NOT_PROD=value
SEMANTIC_CACHE_INDEX_NAME_NOT_PROD=value
COLLECTION_NAME_NOT_PROD=value
TELEGRAM_BOT_TOKEN_NOT_PROD=value
TELEGRAM_BOT_FASTAPI_KEY_NOT_PROD=value

# ==============================================================================
# "On-Off" Environment Routing Flags
# ==============================================================================
# Toggle to switch individual resources between Production and Non-Production
DATABASE_URL_USE_PROD=true
SEMANTIC_CACHE_INDEX_NAME_USE_PROD=true
COLLECTION_NAME_USE_PROD=true

# (Current prod is on the test Qdrant DB)
USE_TEST_QDRANT_DB=false

# Telegram Bot Environment Switch
TELEGRAM_BOT_USE_PROD=false
```

## RAG Evaluation using RAGAS
Ensure you are in the backend directory

```bash
# Generate for a single organization (creates evaluation/data/org_1/ground_truth.jsonl)
uv run python -m evaluation.generate_ground_truth --org-id 1 --limit 30

# Or generate for multiple specific organizations
uv run python -m evaluation.generate_ground_truth --org-id 1 2 3 --limit 30

# Evaluate a single tenant (reads and writes inside evaluation/data/org_1/)
uv run python -m evaluation.run_evaluation --org-id 1 --top-k 5

# Evaluate all tenant folders and produce evaluation/data/multi_tenant_summary.csv
uv run python -m evaluation.run_evaluation --all-orgs --top-k 5
```

## RAG evaluation updated by claude
```bash
cd backend
mkdir -p evaluation/_old && cp evaluation/*.py evaluation/_old/        # back up your current files
# copy every file from this package over backend/evaluation/ (same names; new: compat, common, safety, stats, reporting, import_human_queries)

# A. fastest useful run: re-score your EXISTING ground_truth.jsonl with the fixed retrieval metrics (no answer generation)
uv run python -m evaluation.run_evaluation --org-id 1 --stage retrieval --filename ground_truth.jsonl

# B. build the stronger test sets (standard + colloquial on the same chunks + unanswerable questions)
uv run python -m evaluation.generate_ground_truth --org-id 1 --limit 40 --colloquial-model <a-different-model-if-you-can>
uv run python -m evaluation.run_evaluation --org-id 1 --stage retrieval

# C. full run: answers, judges, Ragas, abstention
uv run python -m evaluation.run_evaluation --org-id 1 --stage all --judge-model <not-the-QA-model-if-you-can>
```