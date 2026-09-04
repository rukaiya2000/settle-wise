# Percolation robustness of the k-NN similarity graph: does removing the
# highest-betweenness "bridge" borrowers fragment the network faster than
# removing an equally-sized random sample would? Same house style as the
# degree-preserving null model in 02_network.R (rewire/recompute/replicate).
#
# Moran's I is deliberately not computed here: the FR layout coordinates
# stored in graph_nodes are a force-directed drawing, not a spatial process
# in the sense Moran's I tests, so an autocorrelation statistic on them
# would be decorative. This percolation curve is the substantive network
# check for this feature instead.

suppressPackageStartupMessages(library(igraph))

# K_NEIGHBOURS in 02_network.R guarantees every node degree >= 20, so this
# graph is provably robust to removal well past 50% of nodes - a 0-50%
# sweep shows a perfectly flat lcc_fraction == 1 - removal_fraction for
# both strategies with zero variance across random reps, which is a real
# property of the graph (bounded minimum degree), not a bug. Targeted
# removal only starts pulling ahead of random once removal passes ~0.65,
# so the sweep goes to 0.9 to actually capture that regime.
REMOVAL_FRACTIONS <- seq(0, 0.9, by = 0.05)
PERCOLATION_REPS <- 30

lcc_fraction <- function(g, removed_ids, n_total) {
  if (length(removed_ids) == 0) return(1)
  g2 <- delete_vertices(g, removed_ids)
  if (vcount(g2) == 0) return(0)
  max(components(g2)$csize) / n_total
}

# Trapezoidal-rule area under the curve, normalised to [0,1] by the x-range,
# so it reads as "average fraction of the network still connected" over the
# removal sweep - not the raw integral.
auc <- function(x, y) sum(diff(x) * (head(y, -1) + tail(y, -1)) / 2) / (max(x) - min(x))

run_percolation <- function(net) {
  log_step("percolation: robustness curve, %d fractions x %d random reps", length(REMOVAL_FRACTIONS), PERCOLATION_REPS)
  g <- net$graph
  n_total <- vcount(g)
  by_betweenness <- net$node_tbl %>% arrange(desc(betweenness)) %>% pull(debt_id)

  targeted <- map_dfr(REMOVAL_FRACTIONS, function(f) {
    k <- round(f * n_total)
    tibble(removal_fraction = f, strategy = "targeted", n_removed = k,
           lcc_fraction = lcc_fraction(g, by_betweenness[seq_len(k)], n_total),
           lcc_fraction_sd = NA_real_, n_reps = 1L)
  })

  set.seed(SEED)
  random <- map_dfr(REMOVAL_FRACTIONS, function(f) {
    k <- round(f * n_total)
    vals <- replicate(PERCOLATION_REPS, lcc_fraction(g, sample(V(g)$name, k), n_total))
    tibble(removal_fraction = f, strategy = "random", n_removed = k,
           lcc_fraction = mean(vals), lcc_fraction_sd = sd(vals), n_reps = PERCOLATION_REPS)
  })

  curve <- bind_rows(targeted, random) %>% mutate(graph_version = GRAPH_VERSION)
  write_table("network_robustness", curve)

  auc_t <- auc(targeted$removal_fraction, targeted$lcc_fraction)
  auc_r <- auc(random$removal_fraction, random$lcc_fraction)
  gap <- auc_r - auc_t
  n_bridge <- sum(net$node_tbl$is_bridge)

  # A single average gap over the whole sweep dilutes the finding if most of
  # the range is a flat plateau (which it is here, up to ~0.6, courtesy of
  # the k-NN graph's minimum degree). The more informative number is where
  # targeted first drops meaningfully below random's own noise band -
  # "meaningfully" defined as more than 2 random-removal SDs below the
  # random mean, so a one-off dip isn't mistaken for a real divergence.
  diverges <- targeted$lcc_fraction < (random$lcc_fraction - 2 * pmax(random$lcc_fraction_sd, 1e-6))
  onset <- if (any(diverges)) min(targeted$removal_fraction[diverges]) else NA_real_
  # Report the fraction with the single largest targeted-vs-random gap, not
  # the last point in the sweep - the two curves both collapse toward zero
  # near the far end of the range (too few nodes left for either strategy
  # to matter), which would understate the finding if quoted verbatim.
  widest <- which.max(random$lcc_fraction - targeted$lcc_fraction)

  interpretation <- if (!is.na(onset)) {
    sprintf(
      "Both removal strategies leave the network fully robust up to about %.0f%% of borrowers removed - a side effect of every borrower having at least %d nearest-neighbour edges by construction. Past %.0f%% removed, targeted removal of the highest-betweenness borrowers starts fragmenting the network measurably faster than an equally-sized random removal (more than 2 standard deviations below the random baseline). The gap is widest at %.0f%% removed: targeted leaves %.0f%% of the network connected vs %.0f%% for random. That gap is evidence the bridge borrowers marked in the network chart are structurally load-bearing once enough of the graph is gone, even though no small removal set can fragment it on its own.",
      100 * onset, min(degree(net$graph)), 100 * onset,
      100 * targeted$removal_fraction[widest], 100 * targeted$lcc_fraction[widest], 100 * random$lcc_fraction[widest]
    )
  } else {
    sprintf(
      "Across the whole tested range (up to %.0f%% of borrowers removed), targeted removal of the highest-betweenness borrowers never fragments the network meaningfully faster than an equally-sized random removal. That is itself informative: with every borrower guaranteed at least %d nearest-neighbour edges by construction, the network has enough redundant connectivity that no single, realistically-sized set of 'bridge' borrowers is a single point of failure for the behavioural segments.",
      100 * max(REMOVAL_FRACTIONS), min(degree(net$graph))
    )
  }

  summary_row <- tibble(
    graph_version = GRAPH_VERSION, auc_targeted = auc_t, auc_random_mean = auc_r,
    auc_random_sd = mean(random$lcc_fraction_sd, na.rm = TRUE), robustness_gap = gap,
    onset_fraction = onset, n_bridge_nodes = n_bridge, interpretation = interpretation, created_at = NOW)
  write_table("network_robustness_summary", summary_row)
  log_step("percolation: AUC targeted=%.3f random=%.3f gap=%.3f onset=%s", auc_t, auc_r, gap,
           if (is.na(onset)) "none" else sprintf("%.2f", onset))
  list(curve = curve, summary = summary_row)
}
