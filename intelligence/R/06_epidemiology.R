# S -> Active -> {Recovered | Escalated}, restated from the same survival
# basis 03_statistics.R already fits (days_to_payment/observed). The exit
# day and exit reason for every historical borrower come straight from
# intel_borrowers, so the cumulative Recovered count here is numerically
# tied to 1 - KM survival, just viewed as counts over calendar time instead
# of a probability over time-since-open.
#
# R_eff = beta x c x D is NOT an epidemic growth rate: there is no
# borrower-to-borrower transmission. It measures whether outreach resolves
# accounts faster than they age into escalation or the horizon - load on
# the collections process, not contagion. Say so in the UI, not just here.

suppressPackageStartupMessages(library(survival))

EPI_VERSION <- "epi-v1"
R_EFF_BOOT_R <- 300

r_eff_components <- function(node_seg, events_seg, tau) {
  attempts <- events_seg %>% filter(event_type == "call_attempt")
  beta <- if (nrow(attempts)) mean(attempts$outcome == "answered_paid") else NA_real_
  c_rate <- sum(node_seg$n_calls) / sum(node_seg$days_to_payment)
  fit <- survfit(Surv(days_to_payment, observed) ~ 1, data = node_seg)
  d <- unname(summary(fit, rmean = tau)$table["rmean"])
  list(n = nrow(node_seg), beta = beta, beta_n = nrow(attempts), c = c_rate,
       total_calls = sum(node_seg$n_calls), total_days = sum(node_seg$days_to_payment),
       d = d, r_eff = beta * c_rate * d)
}

# Cluster bootstrap at the borrower level: resample debt_ids with
# replacement, pull each resampled borrower's row and all of their call
# events, recompute beta/c/D/R_eff on the resample. Not a call to
# 00_setup.R's boot_ci() - that helper resamples a single numeric vector by
# cluster; R_eff is a nonlinear product of three segment-level ratios, so it
# needs its own replicate() loop, same seeded-cluster-resample style.
r_eff_boot_ci <- function(node_seg, events_seg, tau, R = R_EFF_BOOT_R) {
  set.seed(SEED)
  ev_by_id <- split(events_seg, events_seg$debt_id)
  ids <- node_seg$debt_id
  reps <- replicate(R, {
    samp <- sample(ids, length(ids), replace = TRUE)
    ns <- node_seg[match(samp, node_seg$debt_id), ]
    es <- bind_rows(ev_by_id[samp])
    tryCatch(r_eff_components(ns, es, tau)$r_eff, error = function(e) NA_real_)
  })
  unname(quantile(reps, c(0.025, 0.975), na.rm = TRUE))
}

run_epidemiology <- function(ctx, net) {
  log_step("epidemiology: building state curves and R_eff")
  hist_b <- ctx$borrowers %>% filter(cohort == "historical")
  nb <- net$node_tbl %>%
    left_join(hist_b %>% select(debt_id, opened_at, closed_at, final_outcome), by = "debt_id") %>%
    mutate(
      opened_date = as.Date(opened_at),
      exit_date = opened_date + round(days_to_payment),
      # observed==1 means "made at least one payment" (matches the `paid`
      # column semantics used throughout this codebase), not "fully
      # cleared" - so a borrower can be observed==1 and still end up
      # needs_review on the remainder. Counted as recovered here since
      # that's the event the survival analysis is built on; disclosed via
      # n_edge_case below rather than silently reclassified.
      state_at_exit = case_when(
        observed == 1 ~ "recovered",
        observed == 0 & final_outcome == "needs_review" ~ "escalated",
        TRUE ~ "still_active"
      )
    )

  n_edge_case <- sum(nb$observed == 1 & nb$final_outcome == "needs_review")

  horizon <- max(nb$exit_date[nb$state_at_exit == "still_active"], na.rm = TRUE)
  all_days <- seq(min(nb$opened_date), horizon, by = "day")

  cum_by_day <- function(df, date_col) {
    df %>% count(day = {{ date_col }}, name = "n") %>%
      complete(day = all_days, fill = list(n = 0)) %>% arrange(day) %>% pull(n) %>% cumsum()
  }

  build_curve <- function(df, label) {
    n_cohort <- nrow(df)
    cum_opened <- cum_by_day(df, opened_date)
    cum_rec <- cum_by_day(df %>% filter(state_at_exit == "recovered"), exit_date)
    cum_esc <- cum_by_day(df %>% filter(state_at_exit == "escalated"), exit_date)
    tibble(day = as.character(all_days), segment_label = label,
           n_susceptible = n_cohort - cum_opened, n_active = cum_opened - cum_rec - cum_esc,
           n_recovered = cum_rec, n_escalated = cum_esc, n_cohort = n_cohort)
  }

  seg_labels <- sort(unique(nb$segment_label))
  curve <- bind_rows(
    build_curve(nb, "All segments"),
    map_dfr(seg_labels, ~ build_curve(nb %>% filter(segment_label == .x), .x))
  ) %>% mutate(graph_version = GRAPH_VERSION, epi_version = EPI_VERSION, created_at = NOW)

  stopifnot(all(with(curve, n_susceptible + n_active + n_recovered + n_escalated == n_cohort)))
  write_table("epi_curve_daily", curve)

  events_hist <- ctx$events %>% filter(cohort == "historical", event_type == "call_attempt")
  tau <- min(tapply(nb$days_to_payment, nb$segment_label, max, na.rm = TRUE))
  note <- sprintf(
    "No borrower-to-borrower transmission: R_eff = beta x c x D reuses the epidemic formula to ask whether outreach converts accounts faster than they age into escalation or the %d-day observation window, not to predict runaway growth. %d of %d borrowers (%.1f%%) both made a payment and were later escalated; they are counted as 'recovered' here since that is the event the survival analysis (and this metric) is built on.",
    round(tau), n_edge_case, nrow(nb), 100 * n_edge_case / nrow(nb))

  reproduction <- map_dfr(c("All segments", seg_labels), function(lab) {
    ns <- if (lab == "All segments") nb else nb %>% filter(segment_label == lab)
    es <- events_hist %>% filter(debt_id %in% ns$debt_id)
    comp <- r_eff_components(ns, es, tau)
    ci <- r_eff_boot_ci(ns, es, tau)
    tibble(segment_label = lab, n = comp$n, beta = comp$beta, beta_n_attempts = comp$beta_n,
           c_contacts_per_active_day = comp$c, total_calls = comp$total_calls,
           total_active_days = comp$total_days, d_days = comp$d, d_tau_days = tau,
           r_eff = comp$r_eff, r_eff_ci_low = ci[1], r_eff_ci_high = ci[2], limitation_note = note)
  }) %>% mutate(epi_version = EPI_VERSION, created_at = NOW)

  write_table("epi_reproduction", reproduction)
  log_step("epidemiology: %d curve rows, %d segments, tau=%.1fd", nrow(curve), nrow(reproduction), tau)
  list(curve = curve, reproduction = reproduction)
}
