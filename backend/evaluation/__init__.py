"""RAG evaluation suite (read-only against production).

Layers
  1. safety.py            - guards that make it impossible for an eval run to write to Postgres / Qdrant / Redis
  2. generate_ground_truth.py / import_human_queries.py - build the test sets
  3. pipeline_inspector.py - runs the production retrieval path and records every stage
  4. run_evaluation.py     - scores retrieval (per stage), reranker effect, context presence, answers, abstention
  5. reporting.py / stats.py - confidence intervals, paired tests, markdown report

See evaluation/README_EVAL.md for the full walkthrough.
"""
