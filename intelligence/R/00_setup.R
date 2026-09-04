# Shared setup for the intelligence pipeline.
#
# Everything reads from and writes back to the same SQLite database the
# Python service uses (data/settlewise.db). Python owns the schema
# (server/intelligence/schema.py); R replaces table contents wholesale with
# dbWriteTable(overwrite = TRUE) so a rerun is always a clean rebuild.

suppressPackageStartupMessages({
  library(DBI)
  library(RSQLite)
  library(dplyr)
  library(tidyr)
  library(tibble)
  library(purrr)
  library(stringr)
  library(jsonlite)
})

# Scripts are run from intelligence/ (run_all.R does setwd); the report is
# rendered from there too. Anything else is treated as the repo root.
PROJECT_ROOT <- normalizePath(getwd(), mustWork = FALSE)
if (basename(PROJECT_ROOT) == "intelligence") PROJECT_ROOT <- dirname(PROJECT_ROOT)
DB_PATH <- Sys.getenv("DB_PATH", file.path(PROJECT_ROOT, "data", "settlewise.db"))
# .env/.env.example ship DB_PATH as "./data/settlewise.db" - correct for the
# Python process, which always runs from the repo root, but this same env
# var is inherited verbatim when the FastAPI /rebuild route spawns `make
# intelligence` as a subprocess, and by then the Makefile has already `cd
# intelligence`'d - a relative DB_PATH silently resolves against the wrong
# directory ("unable to open database file"). Anchor it to PROJECT_ROOT
# whenever it isn't already absolute, regardless of where this process's
# cwd happens to be.
if (!grepl("^(/|[A-Za-z]:)", DB_PATH)) DB_PATH <- file.path(PROJECT_ROOT, DB_PATH)
SYNTH_DIR <- file.path(PROJECT_ROOT, "data", "synthetic")
OUTPUT_DIR <- file.path(PROJECT_ROOT, "intelligence", "output")
dir.create(OUTPUT_DIR, showWarnings = FALSE, recursive = TRUE)

SEED <- 20260903
FEATURE_VERSION <- "features-v1"
GRAPH_VERSION <- "knn-cosine-k10-louvain-v1"
ANALYSIS_VERSION <- "stats-v1"
NOW <- format(Sys.time(), "%Y-%m-%dT%H:%M:%S")

db <- function() dbConnect(SQLite(), DB_PATH)

read_table <- function(name) {
  con <- db(); on.exit(dbDisconnect(con))
  as_tibble(dbReadTable(con, name))
}

write_table <- function(name, df) {
  con <- db(); on.exit(dbDisconnect(con))
  df <- as.data.frame(df)
  # SQLite has no logical type; store flags as integers so Python sees 0/1.
  for (col in names(df)) if (is.logical(df[[col]])) df[[col]] <- as.integer(df[[col]])
  dbWriteTable(con, name, df, overwrite = TRUE)
  invisible(nrow(df))
}

log_step <- function(...) cat(format(Sys.time(), "%H:%M:%S"), "-", sprintf(...), "\n")

# Bootstrap CI for a mean/proportion, resampling at the borrower level when
# a cluster id is supplied (call attempts within a borrower are not
# independent, so a naive per-row bootstrap understates uncertainty).
boot_ci <- function(x, cluster = NULL, R = 500, stat = mean, conf = 0.95, seed = SEED) {
  set.seed(seed)
  x <- x[!is.na(x)]
  if (length(x) == 0) return(c(NA_real_, NA_real_))
  if (is.null(cluster)) {
    reps <- replicate(R, stat(sample(x, replace = TRUE)))
  } else {
    cl <- split(x, cluster[!is.na(x)])
    reps <- replicate(R, stat(unlist(cl[sample(length(cl), replace = TRUE)], use.names = FALSE)))
  }
  a <- (1 - conf) / 2
  unname(quantile(reps, c(a, 1 - a), na.rm = TRUE))
}

`%||%` <- function(a, b) if (is.null(a)) b else a
