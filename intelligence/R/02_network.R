# Behavioural similarity network.
#
# Nodes are historical borrowers; an edge joins each borrower to its k most
# similar peers by cosine similarity of standardised contact-behaviour
# features (see NETWORK_FEATURES). The graph is undirected, so a borrower
# can end up with more than k edges if it is in many others' neighbour
# lists - those "popular" nodes are exactly the ones worth looking at.
#
# Three things come out of it:
#   1. Communities (Louvain) -> behavioural segments, labelled by profile.
#   2. Betweenness -> "bridge" borrowers who sit between segments.
#   3. Nearest neighbours -> the cohort a live borrower is compared to.
# Plus a null model: degree-preserving rewiring, to show the modularity is
# not just what any graph with these degrees would give.

suppressPackageStartupMessages(library(igraph))

K_NEIGHBOURS <- 20
# Louvain over-partitions k-NN graphs at the default resolution (every
# dense neighbourhood becomes its own community). 0.5 was chosen on a
# sweep of k in {10,20,30} x resolution in {0.3,0.5,1}; see report.qmd.
LOUVAIN_RESOLUTION <- 0.5
N_NULL <- 50
BRIDGE_QUANTILE <- 0.95

label_communities <- function(profiles) {
  # Assign a plain-English label to each community from its profile. The
  # archetypes are ordered; each community takes the closest unused one,
  # and a second community matching the same archetype gets a suffix so
  # labels stay unique. Labels are for humans - the community id is the key.
  archetypes <- tibble(
    label = c("Prompt payers", "Delayed but responsive", "Hardship", "Hard to reach"),
    contact = c(0.62, 0.45, 0.50, 0.15),
    evening_lift = c(0.04, 0.40, 0.04, 0.05),
    objection = c(0.10, 0.14, 0.38, 0.12),
    refusal = c(0.06, 0.08, 0.08, 0.36)
  )
  out <- character(nrow(profiles))
  used <- integer(0)
  ord <- order(-profiles$n)
  for (i in ord) {
    d <- with(archetypes, (contact - profiles$contact_success_rate[i])^2 +
                (evening_lift - profiles$evening_lift[i])^2 +
                (objection - profiles$objection_rate[i])^2 +
                (refusal - profiles$refusal_rate[i])^2)
    best <- which.min(d)
    lab <- archetypes$label[best]
    if (best %in% used) lab <- paste0(lab, " (", sum(used == best) + 1, ")")
    used <- c(used, best)
    out[i] <- lab
  }
  out
}

run_network <- function(feats, borrowers) {
  log_step("network: building k-NN graph (k=%d)", K_NEIGHBOURS)
  hist <- feats %>% filter(cohort == "historical")
  live <- feats %>% filter(cohort == "live")
  Z <- network_matrix(hist)
  S <- cosine_similarity(Z)
  diag(S) <- -Inf

  # k nearest per node -> undirected edge list (deduplicated).
  nn <- t(apply(S, 1, function(r) order(r, decreasing = TRUE)[1:K_NEIGHBOURS]))
  edges <- tibble(
    source = rep(rownames(Z), each = K_NEIGHBOURS),
    target = rownames(Z)[as.vector(t(nn))],
    weight = S[cbind(rep(seq_len(nrow(Z)), each = K_NEIGHBOURS), as.vector(t(nn)))]
  ) %>%
    mutate(a = pmin(source, target), b = pmax(source, target)) %>%
    distinct(a, b, .keep_all = TRUE) %>%
    transmute(source = a, target = b, weight = pmax(weight, 1e-3))

  g <- graph_from_data_frame(edges, directed = FALSE, vertices = tibble(name = rownames(Z)))
  set.seed(SEED)
  comm <- cluster_louvain(g, weights = E(g)$weight, resolution = LOUVAIN_RESOLUTION)
  membership <- membership(comm)
  mod <- modularity(g, membership, weights = E(g)$weight)
  log_step("network: %d nodes, %d edges, %d communities, modularity %.3f", vcount(g), ecount(g), length(unique(membership)), mod)

  # Degree-preserving null: is this modularity more than the degree
  # sequence alone would give? Rewire keeps every node's degree, destroys
  # the structure, then Louvain on that.
  null_mod <- replicate(N_NULL, {
    gr <- rewire(g, with = keeping_degseq(niter = ecount(g) * 5))
    modularity(gr, membership(cluster_louvain(gr, resolution = LOUVAIN_RESOLUTION)))
  })

  btw <- betweenness(g, weights = 1 / E(g)$weight, normalized = TRUE)
  deg <- degree(g)
  bridge_cut <- quantile(btw, BRIDGE_QUANTILE)

  # Community profiles: how each segment actually behaves and pays. Payment
  # rate comes from intel_borrowers, which the graph never saw.
  node_tbl <- tibble(debt_id = names(membership), community = as.integer(membership), degree = as.integer(deg[debt_id]),
                     betweenness = as.numeric(btw[debt_id]), is_bridge = betweenness >= bridge_cut) %>%
    left_join(hist, by = "debt_id") %>%
    left_join(borrowers %>% select(debt_id, paid, days_to_payment, observed, strategy), by = "debt_id")

  profiles <- node_tbl %>%
    group_by(community) %>%
    summarise(
      n = n(),
      payment_rate = mean(paid),
      ci = list(boot_ci(paid)),
      contact_success_rate = mean(contact_success_rate),
      evening_lift = mean(coalesce(evening_contact_rate, contact_success_rate) - coalesce(daytime_contact_rate, contact_success_rate)),
      objection_rate = mean(objection_rate),
      refusal_rate = mean(refusal_rate),
      median_days_to_payment = median(days_to_payment[observed == 1], na.rm = TRUE),
      .groups = "drop"
    ) %>%
    mutate(ci_low = map_dbl(ci, 1), ci_high = map_dbl(ci, 2)) %>% select(-ci)

  # Best hour bucket per community: answer rate by bucket over its calls.
  events <- read_table("interaction_events") %>% filter(event_type == "call_attempt", cohort == "historical")
  best_bucket <- events %>%
    inner_join(node_tbl %>% select(debt_id, community), by = "debt_id") %>%
    group_by(community, time_bucket) %>% summarise(rate = mean(outcome != "no_answer"), n = n(), .groups = "drop") %>%
    filter(n >= 20) %>%
    arrange(community, desc(rate)) %>% group_by(community) %>% slice(1) %>% ungroup() %>%
    select(community, best_bucket = time_bucket, best_bucket_rate = rate)

  profiles <- profiles %>% left_join(best_bucket, by = "community")
  profiles$segment_label <- label_communities(profiles)
  profiles <- profiles %>% mutate(description = sprintf(
    "%d borrowers; %.0f%% pick up; %.0f%% paid (95%% CI %.0f-%.0f%%); best window %s",
    n, 100 * contact_success_rate, 100 * payment_rate, 100 * ci_low, 100 * ci_high, coalesce(best_bucket, "n/a")))

  node_tbl <- node_tbl %>% left_join(profiles %>% select(community, segment_label), by = "community")

  # Live borrowers: place them by nearest historical neighbours (majority
  # community). They are not graph nodes - they are queries against it.
  Zl <- network_matrix(live, attr(Z, "center"), attr(Z, "scale"))
  Sl <- cosine_similarity(Zl, Z)
  nn_l <- t(apply(Sl, 1, function(r) order(r, decreasing = TRUE)[1:K_NEIGHBOURS]))
  live_assign <- tibble(debt_id = rownames(Zl)) %>%
    mutate(community = map_int(seq_len(n()), function(i) {
      cm <- node_tbl$community[match(rownames(Z)[nn_l[i, ]], node_tbl$debt_id)]
      as.integer(names(which.max(table(cm))))
    })) %>%
    left_join(profiles %>% select(community, segment_label), by = "community") %>%
    mutate(degree = NA_integer_, betweenness = NA_real_, is_bridge = FALSE, assigned_via = "knn_vote")

  segments <- bind_rows(
    node_tbl %>% transmute(debt_id, community, segment_label, degree, betweenness, is_bridge, assigned_via = "louvain"),
    live_assign %>% select(debt_id, community, segment_label, degree, betweenness, is_bridge, assigned_via)
  ) %>% mutate(graph_version = GRAPH_VERSION)

  # Neighbour lists: top-k historical peers for every borrower, with what
  # happened to them. This is what "Borrowers like this one" shows.
  neighbour_rows <- function(ids, nn_mat, sim_mat) {
    map_dfr(seq_along(ids), function(i) {
      nb <- rownames(Z)[nn_mat[i, ]]
      tibble(debt_id = ids[i], neighbor_id = nb, rank = seq_along(nb),
             similarity = sim_mat[i, nn_mat[i, ]])
    })
  }
  neighbours <- bind_rows(
    neighbour_rows(rownames(Z), nn, S),
    neighbour_rows(rownames(Zl), nn_l, Sl)
  ) %>%
    left_join(node_tbl %>% select(neighbor_id = debt_id, neighbor_paid = paid, neighbor_segment = segment_label,
                                  neighbor_days_to_payment = days_to_payment, neighbor_best_bucket = preferred_bucket), by = "neighbor_id")

  # Layout for the dashboard, computed here so the browser only draws.
  set.seed(SEED)
  lay <- layout_with_fr(g, weights = E(g)$weight)
  lay <- scale(lay)
  nodes_out <- node_tbl %>% transmute(debt_id, community, segment_label, x = lay[match(debt_id, V(g)$name), 1],
                                      y = lay[match(debt_id, V(g)$name), 2], degree, betweenness, is_bridge, paid, cohort)

  # Evaluation against the hidden labels. Only this block reads the truth.
  ari <- NA_real_
  truth_path <- file.path(SYNTH_DIR, "ground_truth.json")
  if (file.exists(truth_path)) {
    truth <- fromJSON(truth_path)$segments
    t_lab <- unlist(truth[node_tbl$debt_id])
    ari <- compare(as.integer(factor(t_lab)), node_tbl$community, method = "adjusted.rand")
    log_step("network: adjusted Rand index vs planted segments = %.3f", ari)
  }

  metrics <- tibble(graph_version = GRAPH_VERSION, built_at = NOW, n_nodes = vcount(g), n_edges = ecount(g), k = K_NEIGHBOURS,
                    n_communities = length(unique(membership)), modularity = mod,
                    null_modularity_mean = mean(null_mod), null_modularity_sd = sd(null_mod), ari_vs_truth = ari,
                    edge_definition = sprintf("cosine similarity on standardised [%s]; each node linked to its %d nearest; undirected", paste(NETWORK_FEATURES, collapse = ", "), K_NEIGHBOURS))

  write_table("borrower_segments", segments)
  write_table("segment_profiles", profiles %>% select(community, segment_label, n, payment_rate, ci_low, ci_high, best_bucket, best_bucket_rate,
                                                       median_days_to_payment, contact_success_rate, description))
  write_table("borrower_neighbors", neighbours)
  write_table("graph_nodes", nodes_out)
  write_table("graph_edges", edges)
  write_table("network_metrics", metrics)
  # Mirror the in-memory return value below field-for-field: 04_model.R's
  # live-prediction block reads net$segments, which only exists here when
  # this run was cached and reloaded (e.g. `Rscript run_all.R model` alone)
  # rather than freshly computed in the same session.
  saveRDS(list(graph = g, segments = segments, membership = membership, Z = Z, node_tbl = node_tbl, profiles = profiles, null_mod = null_mod), file.path(OUTPUT_DIR, "network.rds"))
  list(graph = g, segments = segments, profiles = profiles, node_tbl = node_tbl, metrics = metrics, Z = Z, null_mod = null_mod)
}
