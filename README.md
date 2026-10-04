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
```