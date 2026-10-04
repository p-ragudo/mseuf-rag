from app.services.embeddings.factory import get_embedder
import asyncio

embedder = get_embedder()
print("Provider loaded:", type(embedder).__name__)
print("Dimension:", embedder.dimension)

res = asyncio.run(embedder.embed(["MSEUF BSCS curriculum"]))
print("Vector size:", len(res[0].values))
assert len(res[0].values) == 1024, "Expected 1024-dim output for BGE-M3"
print("OK: BGE-M3 embedding generated successfully!")