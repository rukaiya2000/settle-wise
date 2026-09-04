#!/usr/bin/env Rscript
# Run the whole intelligence pipeline against data/settlewise.db.
#
#   cd intelligence && Rscript run_all.R            # everything
#   cd intelligence && Rscript run_all.R network    # one stage (after features)
#
# Stages, in order: features -> network -> epidemiology -> percolation ->
# statistics -> model -> evaluate. Each stage writes its tables back to
# SQLite; the Python API only ever reads those tables, so once this
# finishes the dashboard is live.
#
# epidemiology/percolation run before statistics/model deliberately: both
# only need ctx/net, and 04_model.R has a known pre-existing bug that halts
# the script, so anything placed after it would silently never run on a
# normal `make intelligence`.

args <- commandArgs(trailingOnly = TRUE)
script <- sub("--file=", "", grep("--file=", commandArgs(), value = TRUE)[1])
if (!is.na(script)) setwd(dirname(normalizePath(script)))

for (f in sort(list.files("R", full.names = TRUE))) source(f)

t0 <- Sys.time()
stages <- if (length(args)) args else c("features", "network", "epidemiology", "percolation", "statistics", "model", "evaluate")

ctx <- run_features()
if ("network" %in% stages) net <- run_network(ctx$features, ctx$borrowers) else net <- readRDS(file.path(OUTPUT_DIR, "network.rds"))
if ("epidemiology" %in% stages) epi <- run_epidemiology(ctx, net)
if ("percolation" %in% stages) perc <- run_percolation(net)
if ("statistics" %in% stages) stats <- run_statistics(ctx, net)
if ("model" %in% stages) model <- run_model(ctx, net)
if ("evaluate" %in% stages) run_evaluation(ctx, net)

log_step("done in %.1fs", as.numeric(difftime(Sys.time(), t0, units = "secs")))
