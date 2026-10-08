import os
import sys

TARGET_VARS = sorted([
    "CHUNK_COLLECTION_NAME",
    "COLLECTION_NAME",
    "DATABASE_URL",
    "DATABASE_URL_NOT_PROD",
    "DATABASE_URL_USE_PROD",
    "DEFAULT_TOP_K",
    "DENSE_COLLECTION_NAME",
    "DEVELOPMENT",
    "EMBEDDING_API_KEY",
    "EMBEDDING_DIMENSION",
    "EMBEDDING_MODEL",
    "EMBEDDING_PROVIDER",
    "EMBEDDING_TASK_TYPE",
    "HF_TOKEN",
    "HOST",
    "LLM_QA_API_KEY",
    "LLM_QA_MODEL",
    "LLM_QA_PROVIDER",
    "LLM_QGEN_API_KEY",
    "LLM_QGEN_MODEL",
    "LLM_QGEN_PROVIDER",
    "MAX_TOP_K",
    "MIN_TOP_K",
    "PORT",
    "QDRANT_API_KEY",
    "QDRANT_CLUSTER_ENDPOINT",
    "QDRANT_EMBEDDING_MODEL",
    "SCRIPT_QGEN_MIN_WORDS_PER_CHUNK",
    "SCRIPT_QGEN_USE_REAL_DATA",
    "SECRET_KEY",
    "SEMANTIC_CACHE_INDEX_NAME",
    "SEMANTIC_CACHE_PROVIDER",
    "SEMANTIC_CACHE_THRESHOLD",
    "SEMANTIC_CACHE_TTL_SECONDS",
    "SEMANTIC_CACHE_URL",
    "SPARSE_COLLECTION_NAME",
    "TARGET_DOMAIN",
    "TELEGRAM_BOT_FASTAPI_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TEST_DOMAIN",
    "TEST_QDRANT_API_KEY",
    "TEST_QDRANT_CLUSTER_ENDPOINT",
    "TEST_TARGET_DOMAIN",
    "USE_TEST_QDRANT_DB",
    "VECTOR_DB_EMBEDDING_MODEL",
    "VECTOR_DB_PROVIDER",
    "VECTOR_DIM",
])


def main():
    write_to_file = "--save" in sys.argv or "-s" in sys.argv
    lines = []

    for key in TARGET_VARS:
        if key in os.environ:
            val = os.environ[key]
            lines.append(f'{key}={val}')

    output = "\n".join(lines)
    print(output)

    if write_to_file:
        target_path = ".env"
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(output + "\n")
        print(f"\n[Saved to {os.path.abspath(target_path)}]", file=sys.stderr)


if __name__ == "__main__":
    main()