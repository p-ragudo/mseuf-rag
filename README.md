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
