import os
import tempfile
import httpx
from qdrant_client import QdrantClient
from app.core.config import settings

CLUSTER_URL = (
    settings.test_qdrant_cluster_endpoint
    if settings.use_test_qdrant_db
    else settings.qdrant_cluster_endpoint
).rstrip("/")

API_KEY = (
    settings.test_qdrant_api_key
    if settings.use_test_qdrant_db
    else settings.qdrant_api_key
)

client = QdrantClient(
    url=CLUSTER_URL,
    api_key=API_KEY,
    timeout=900.0,
)

source_collection = settings.collection_name
target_collection = settings.collection_name_not_prod

print(f"Source Collection: '{source_collection}'")
print(f"Target Collection: '{target_collection}'")

print(f"Checking existing snapshots for '{source_collection}'...")
existing_snapshots = client.list_snapshots(collection_name=source_collection)

if existing_snapshots:
    latest = sorted(existing_snapshots, key=lambda s: s.creation_time or "", reverse=True)[0]
    snapshot_name = latest.name
    print(f"Found existing snapshot: {snapshot_name} ({latest.size / (1024 * 1024):.2f} MB)")
else:
    print(f"Creating new snapshot for '{source_collection}'...")
    snapshot_info = client.create_snapshot(
        collection_name=source_collection,
        wait=True
    )
    snapshot_name = snapshot_info.name
    print(f"Snapshot created successfully: {snapshot_name}")

with tempfile.TemporaryDirectory() as tmp_dir:
    temp_snapshot_path = os.path.join(tmp_dir, snapshot_name)
    headers = {"api-key": API_KEY} if API_KEY else {}

    download_url = f"{CLUSTER_URL}/collections/{source_collection}/snapshots/{snapshot_name}"
    print("Downloading snapshot...")
    with httpx.Client(timeout=900.0) as http_client:
        with http_client.stream("GET", download_url, headers=headers) as response:
            response.raise_for_status()
            with open(temp_snapshot_path, "wb") as f:
                for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                    f.write(chunk)

    print(f"Downloaded {os.path.getsize(temp_snapshot_path) / (1024 * 1024):.2f} MB.")

    upload_url = f"{CLUSTER_URL}/collections/{target_collection}/snapshots/upload?wait=true"
    print(f"Restoring into target '{target_collection}' on Qdrant Cloud...")
    with open(temp_snapshot_path, "rb") as snapshot_file:
        files = {"snapshot": (snapshot_name, snapshot_file, "application/octet-stream")}
        with httpx.Client(timeout=900.0) as http_client:
            res = http_client.post(upload_url, headers=headers, files=files)
            res.raise_for_status()

src_count = client.count(source_collection).count
tgt_count = client.count(target_collection).count

print("\nVerification Results:")
print(f"  Source collection ('{source_collection}'): {src_count} points")
print(f"  Target collection ('{target_collection}'): {tgt_count} points")
assert src_count == tgt_count, "Point count mismatch between source and target!"
print("\nDuplication complete!")