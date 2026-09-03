"""Intelligence layer: analytics tables, synthetic history, and the
recommendation composer.

The split is deliberate. Python owns the operational service and the
deterministic glue - event extraction, the analytics schema, and turning
stored analysis into a recommendation. All actual analysis (the similarity
network, the statistics, the model) lives in R under intelligence/ and
writes its results back into the same SQLite database. Nothing here
computes a probability or a p-value; it only reads what R produced.
"""
