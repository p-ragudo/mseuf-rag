import os
from pathlib import Path
from huggingface_hub import snapshot_download

# Target folder inside backend
BASE_DIR = Path(__file__).resolve().parent.parent
TARGET_DIR = BASE_DIR / "local_models" / "bge-m3"

def download():
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    
    # Check if weights are already present
    if (TARGET_DIR / "model.safetensors").exists():
        print(f"[Model Setup] Model already exists at {TARGET_DIR}")
        return

    print(f"[Model Setup] Downloading BAAI/bge-m3 to {TARGET_DIR}...")
    
    # Route through mirror to bypass datacenter IP rate limits
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

    snapshot_download(
        repo_id="BAAI/bge-m3",
        local_dir=str(TARGET_DIR),
        local_dir_use_symlinks=False,
        resume_download=True,
    )
    print(f"[Model Setup] Successfully downloaded BAAI/bge-m3 to {TARGET_DIR}")

if __name__ == "__main__":
    download()