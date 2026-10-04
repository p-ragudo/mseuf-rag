from app.services.embeddings.factory import get_embedder
import asyncio

embedder = get_embedder()
print("Provider loaded:", type(embedder).__name__)
print("Dimension:", embedder.dimension)

res = asyncio.run(embedder.embed(["MSEUF BSCS curriculum"]))
print("Vector size:", len(res[0].values))
assert len(res[0].values) == 768, "Expected 768-dim output for gemini-embedding-2"
print("OK: gemini-embedding-2 embedding generated successfully!")