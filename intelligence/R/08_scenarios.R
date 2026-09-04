# Intervention scenario analysis, in the shape of impact network analysis
# (Garrett et al. 2021, the INA package). INA asks: if a management practice
# is introduced at THESE nodes, adopted with SOME probability, with an effect
# of UNCERTAIN size, what is the outcome across many stochastic realizations,
# compared with introducing it elsewhere? The same question here, with:
#
#   initinfo (where it starts)  -> a targeting rule and a budget k of borrowers
#   probadopt (does it take)    -> the borrower's own historical contact rate:
#                                  an intervention only works on someone reached
#   maneffmean / maneffsd       -> the per-segment odds ratios 03_statistics.R
#                                  estimated, drawn from their 95% CI on every
#                                  realization, so a non-significant effect
#                                  stays small and noisy instead of being
#                                  zeroed by fiat
#   nreals                      -> realizations, with common random numbers so
#                                  every rule is a paired comparison against
#                                  the random-targeting null (as
#                                  07_percolation.R pairs targeted vs random)
#
# What is deliberately NOT here: INA's second layer. Its bioentity spreads
# node to node over a dispersal network; nothing spreads here - one borrower
# paying does not change a neighbour's odds. The similarity network
# contributes exactly one thing, the betweenness ranking behind the "bridge"
# rule, so this is a single-layer scenario analysis and the UI says so.
#
# Baseline P(pay) is the segment's observed payment rate, not the champion
# model: scoring the 1,000 historical borrowers the model was trained on
# would be an in-sample estimate dressed up as a per-borrower one.

SCENARIO_VERSION <- "scenarios-v1"
SCENARIO_REALS <- 200L
SCENARIO_BUDGETS <- c(25L, 50L, 100L, 150L, 200L, 300L, 400L, 500L)
SCENARIO_K_REF <- 100L

# Which estimated effects each intervention applies. Names are the
# statistical_findings.analysis_name values.
SCENARIO_STRATEGIES <- list(
  evening = "contact_time",
  reminder = "reminder",
  evening_reminder = c("contact_time", "reminder")
)
TARGETING_RULES <- c("bridge", "at_risk", "reachable", "random")

odds <- function(p) p / (1 - p)
lift_odds <- function(p, or) {
  o <- odds(pmin(pmax(p, 1e-6), 1 - 1e-6)) * or
  o / (1 + o)
}

# One draw of an odds ratio per realization from its 95% CI: log-normal with
# the standard error implied by the CI width. This is INA's maneffsd.
draw_or <- function(or, lo, hi, n) {
  if (any(is.na(c(or, lo, hi))) || lo <= 0 || hi <= 0) return(rep(1, n))
  se <- (log(hi) - log(lo)) / (2 * qnorm(0.975))
  exp(rnorm(n, log(or), se))
}

# Effect sizes by segment for one analysis (one row per segment; the pooled
# "all" row is deliberately not used - a pooled OR would hand every segment
# the average effect, which is the opposite of what targeting is for).
segment_effects <- function(findings, analysis) {
  findings %>%
    filter(analysis_name == analysis, !is.na(segment_label)) %>%
    select(segment_label, effect_size, ci_low, ci_high, significant)
}

run_scenarios <- function(ctx, net) {
  log_step("scenarios: %d strategies x %d rules x %d budgets x %d realizations",
           length(SCENARIO_STRATEGIES), length(TARGETING_RULES), length(SCENARIO_BUDGETS), SCENARIO_REALS)
  findings <- read_table("statistical_findings")

  nodes <- net$node_tbl %>%
    left_join(net$profiles %>% select(community, p_base = payment_rate), by = "community") %>%
    mutate(reach = coalesce(contact_success_rate, mean(contact_success_rate, na.rm = TRUE)),
           amount_due = coalesce(amount_due, 0))
  n <- nrow(nodes)
  seg <- nodes$segment_label
  seg_levels <- sort(unique(seg))

  # Fixed orderings for the deterministic rules; random is drawn per
  # realization. Budgets are nested (the first k of an ordering), the same
  # way percolation's removal sets are.
  orderings <- list(
    bridge    = order(-nodes$betweenness),
    at_risk   = order(nodes$p_base, -nodes$reach),
    reachable = order(-nodes$reach)
  )

  results <- list()
  for (strategy in names(SCENARIO_STRATEGIES)) {
    analyses <- SCENARIO_STRATEGIES[[strategy]]
    effects <- lapply(analyses, function(a) segment_effects(findings, a))

    set.seed(SEED)
    # Per realization, per segment: one OR draw per applied effect, multiplied.
    # matrix [reals x segments]
    L <- matrix(1, SCENARIO_REALS, length(seg_levels), dimnames = list(NULL, seg_levels))
    for (eff in effects) for (s in seg_levels) {
      row <- eff %>% filter(segment_label == s)
      if (nrow(row)) L[, s] <- L[, s] * draw_or(row$effect_size, row$ci_low, row$ci_high, SCENARIO_REALS)
    }

    acc <- list()
    for (r in seq_len(SCENARIO_REALS)) {
      u_reach <- runif(n); u_pay <- runif(n)
      base_pay <- u_pay < nodes$p_base
      perm <- sample.int(n)
      lift_i <- L[r, seg]
      for (rule in TARGETING_RULES) {
        ord <- if (rule == "random") perm else orderings[[rule]]
        for (k in SCENARIO_BUDGETS) {
          targeted <- logical(n); targeted[ord[seq_len(k)]] <- TRUE
          delivered <- targeted & (u_reach < nodes$reach)
          p_eff <- ifelse(delivered, lift_odds(nodes$p_base, lift_i), nodes$p_base)
          pay <- u_pay < p_eff
          acc[[length(acc) + 1]] <- c(r, match(rule, TARGETING_RULES), k,
                                     sum(base_pay), sum(pay), sum(nodes$amount_due * (pay - base_pay)))
        }
      }
    }
    m <- do.call(rbind, acc)
    colnames(m) <- c("real", "rule", "k", "payers_base", "payers", "dollars_uplift")
    results[[strategy]] <- as_tibble(m) %>%
      mutate(strategy = strategy, targeting = TARGETING_RULES[rule], uplift = payers - payers_base)
  }
  sims <- bind_rows(results)

  curve <- sims %>%
    group_by(strategy, targeting, k) %>%
    summarise(
      n_reals = n(),
      payers_baseline = mean(payers_base),
      payers_mean = mean(payers), payers_sd = sd(payers),
      uplift_mean = mean(uplift), uplift_sd = sd(uplift),
      uplift_ci_low = unname(quantile(uplift, 0.025)), uplift_ci_high = unname(quantile(uplift, 0.975)),
      dollars_uplift_mean = mean(dollars_uplift), dollars_uplift_sd = sd(dollars_uplift),
      .groups = "drop"
    ) %>%
    mutate(k = as.integer(k), n_reals = as.integer(n_reals), graph_version = GRAPH_VERSION, scenario_version = SCENARIO_VERSION)
  write_table("scenario_outcomes", curve)

  limitation <- paste(
    "Single-layer: nothing spreads between borrowers, so this is impact-network-style scenario analysis without INA's dispersal layer;",
    "the network contributes only the betweenness ranking behind the bridge rule.",
    "Baseline P(pay) is the segment's observed payment rate, not a per-borrower model.",
    "Odds ratios estimated on pick-up (evening) and promise completion (reminder) are applied to payment odds directly,",
    "which overstates the effect wherever a pick-up gain does not fully convert to a payment."
  )

  summary <- curve %>% filter(k == SCENARIO_K_REF) %>%
    group_by(strategy) %>%
    group_modify(function(d, key) {
      rnd <- d %>% filter(targeting == "random")
      best <- d %>% filter(targeting != "random") %>% arrange(desc(uplift_mean)) %>% slice(1)
      gap <- best$uplift_mean - rnd$uplift_mean
      gap_sd <- gap / max(rnd$uplift_sd, 1e-6)
      meaningful <- gap_sd > 2
      rule_word <- c(bridge = "the highest-betweenness (bridge) borrowers", at_risk = "the borrowers least likely to pay on their own",
                     reachable = "the borrowers easiest to reach")[best$targeting]
      strat_word <- c(evening = "evening calling", reminder = "an SMS reminder before each promised payment",
                      evening_reminder = "evening calling plus an SMS reminder")[key$strategy]
      interpretation <- sprintf(
        paste0("Giving %d borrowers %s: targeting %s yields %+.1f expected additional payers (SD %.1f, %+.0f dollars) against %+.1f for a random %d",
               " (SD %.1f). That gap of %.1f payers is %s - %.1f random-targeting SDs%s."),
        SCENARIO_K_REF, strat_word, rule_word, best$uplift_mean, best$uplift_sd, best$dollars_uplift_mean,
        rnd$uplift_mean, SCENARIO_K_REF, rnd$uplift_sd, gap,
        if (meaningful) "more than random targeting's own noise" else "within random targeting's own noise", gap_sd,
        if (meaningful) ", so where the intervention lands matters here" else ", so for this intervention the choice of targets is not what drives the outcome")
      # The most INA-relevant sentence on the page. In INA, node position
      # matters because something spreads through the network; here nothing
      # does, so if betweenness targeting sits inside random's noise band
      # that is the expected result, and worth stating rather than hiding.
      bridge <- d %>% filter(targeting == "bridge")
      bridge_sd <- (bridge$uplift_mean - rnd$uplift_mean) / max(rnd$uplift_sd, 1e-6)
      if (abs(bridge_sd) < 1) interpretation <- paste0(interpretation, sprintf(
        " Targeting by network position (bridge borrowers) is indistinguishable from random here (%+.1f SD): betweenness on a similarity network says who resembles whom, not who will respond, because nothing spreads between borrowers - which is exactly the layer this analysis lacks compared with impact network analysis.",
        bridge_sd))
      tibble(best_targeting = best$targeting, uplift_best = best$uplift_mean, uplift_best_sd = best$uplift_sd,
             uplift_random = rnd$uplift_mean, uplift_random_sd = rnd$uplift_sd, gap_vs_random = gap, gap_in_random_sd = gap_sd,
             meaningful = meaningful, k_ref = SCENARIO_K_REF, n_reals = SCENARIO_REALS,
             interpretation = interpretation, limitation_note = limitation)
    }) %>% ungroup() %>%
    mutate(graph_version = GRAPH_VERSION, scenario_version = SCENARIO_VERSION, created_at = NOW)
  write_table("scenario_summary", summary)

  for (i in seq_len(nrow(summary)))
    log_step("scenarios: %s -> best %s %+.1f vs random %+.1f at k=%d (%.1f SD)", summary$strategy[i], summary$best_targeting[i],
             summary$uplift_best[i], summary$uplift_random[i], SCENARIO_K_REF, summary$gap_in_random_sd[i])
  list(curve = curve, summary = summary)
}
