# Statistical analyses. Every finding carries sample size, method, effect
# size, a confidence interval, a p-value, and a limitations line, and all
# p-values are Benjamini-Hochberg adjusted together at the end. The set
# includes one analysis (weekday) that the generator built to be null;
# finding "nothing" there is a result, not a failure.
#
# Uncertainty is bootstrapped at the borrower level where rows are call
# attempts, because attempts within a borrower are not independent.

suppressPackageStartupMessages(library(survival))

finding <- function(id, analysis, question, hypothesis, method, n, effect, effect_label, p, ci, summary, limitations, segment = NA_character_) {
  tibble(finding_id = id, analysis_name = analysis, question = question, hypothesis = hypothesis, method = method,
         sample_size = as.integer(n), effect_size = effect, effect_label = effect_label, p_value = p,
         ci_low = ci[1], ci_high = ci[2], result_summary = summary, limitations = limitations,
         segment_label = segment, created_at = NOW)
}

cramers_v <- function(tab) {
  chi <- suppressWarnings(chisq.test(tab, correct = FALSE))
  unname(sqrt(chi$statistic / (sum(tab) * (min(dim(tab)) - 1))))
}

# Logistic regression of a binary outcome on one binary exposure, returning
# the odds ratio with a Wald CI and the risk difference with a cluster
# bootstrap CI (reusing boot_ci from 00_setup.R rather than re-resampling
# clusters by hand). Used for contact time and for reminders.
binary_effect <- function(df, outcome, exposure, cluster) {
  f <- as.formula(paste(outcome, "~", exposure))
  m <- glm(f, data = df, family = binomial())
  co <- summary(m)$coefficients
  or <- exp(co[2, 1]); or_ci <- exp(co[2, 1] + c(-1, 1) * 1.96 * co[2, 2]); p <- co[2, 4]
  rd_stat <- function(idx) mean(df[[outcome]][idx][df[[exposure]][idx] == 1]) - mean(df[[outcome]][idx][df[[exposure]][idx] == 0])
  rd <- rd_stat(seq_len(nrow(df)))
  rd_ci <- boot_ci(seq_len(nrow(df)), cluster = df[[cluster]], R = 300, stat = rd_stat)
  list(or = or, or_ci = or_ci, p = p, rd = rd, rd_ci = rd_ci,
       n = nrow(df), rate1 = mean(df[[outcome]][df[[exposure]] == 1]), rate0 = mean(df[[outcome]][df[[exposure]] == 0]))
}

run_statistics <- function(ctx, net) {
  log_step("statistics: preparing attempt- and promise-level data")
  events <- ctx$events %>% filter(cohort == "historical")
  borrowers <- ctx$borrowers %>% filter(cohort == "historical")
  seg <- net$segments %>% filter(assigned_via == "louvain") %>% select(debt_id, segment_label)
  attempts <- events %>% filter(event_type == "call_attempt") %>%
    mutate(answered = as.integer(outcome != "no_answer"), evening = as.integer(time_bucket == "evening")) %>%
    left_join(seg, by = "debt_id")
  findings <- list()

  # ---- A. Contact time -----------------------------------------------------
  e <- binary_effect(attempts, "answered", "evening", "debt_id")
  findings$A <- finding("stat_contact_time_all", "contact_time", "Does calling in the evening (17:00-20:00) change the chance the borrower picks up?",
    "P(answer | evening) > P(answer | daytime)", "Logistic regression (answered ~ evening); borrower-clustered bootstrap for the risk difference",
    e$n, e$or, "odds ratio (evening vs daytime)", e$p, e$or_ci,
    sprintf("Pick-up rate %.0f%% in the evening vs %.0f%% in the day (risk difference %+.0f pp, 95%% CI %+.0f to %+.0f). OR %.2f.", 100 * e$rate1, 100 * e$rate0, 100 * e$rd, 100 * e$rd_ci[1], 100 * e$rd_ci[2], e$or),
    "Pooled over all borrowers; the evening_contact strategy over-samples evenings for some borrowers, and the effect is not uniform across segments (see per-segment rows). Observational within strategy.")
  for (s in sort(unique(na.omit(attempts$segment_label)))) {
    d <- attempts %>% filter(segment_label == s)
    if (sum(d$evening) < 30 || sum(1 - d$evening) < 30) next
    e <- binary_effect(d, "answered", "evening", "debt_id")
    findings[[paste0("A_", s)]] <- finding(paste0("stat_contact_time_", gsub("[^a-z0-9]+", "_", tolower(s))), "contact_time",
      sprintf("Within the \"%s\" segment, does evening contact change pick-up?", s), "P(answer | evening) > P(answer | daytime)",
      "Logistic regression within segment; borrower-clustered bootstrap", e$n, e$or, "odds ratio (evening vs daytime)", e$p, e$or_ci,
      sprintf("%.0f%% evening vs %.0f%% daytime (%+.0f pp, CI %+.0f to %+.0f).", 100 * e$rate1, 100 * e$rate0, 100 * e$rd, 100 * e$rd_ci[1], 100 * e$rd_ci[2]),
      "Segment is a graph community, itself estimated from contact behaviour, so this is partly descriptive of how the communities were formed.", segment = s)
  }

  # ---- B. Reminder after a promise -----------------------------------------
  promises <- events %>% filter(outcome == "answered_promised") %>% select(debt_id, promise_time = event_time)
  reminders <- events %>% filter(outcome == "reminder_sent") %>% select(debt_id, rem_time = event_time)
  payments <- events %>% filter(event_type == "payment") %>% select(debt_id, pay_time = event_time)
  prom <- promises %>%
    left_join(reminders, by = "debt_id", relationship = "many-to-many") %>%
    mutate(rem_ok = !is.na(rem_time) & rem_time > promise_time & as.numeric(difftime(as.POSIXct(rem_time), as.POSIXct(promise_time), units = "days")) <= 8) %>%
    group_by(debt_id, promise_time) %>% summarise(reminded = as.integer(any(rem_ok)), .groups = "drop") %>%
    left_join(payments, by = "debt_id", relationship = "many-to-many") %>%
    mutate(pay_ok = !is.na(pay_time) & pay_time > promise_time & as.numeric(difftime(as.POSIXct(pay_time), as.POSIXct(promise_time), units = "days")) <= 10) %>%
    group_by(debt_id, promise_time, reminded) %>% summarise(completed = as.integer(any(pay_ok)), .groups = "drop") %>%
    left_join(seg, by = "debt_id")
  e <- binary_effect(prom, "completed", "reminded", "debt_id")
  findings$B <- finding("stat_reminder_all", "reminder", "Does an SMS reminder the day before a promised payment make the payment more likely?",
    "P(completed | reminded) > P(completed | not reminded)", "Logistic regression (completed ~ reminded); borrower-clustered bootstrap",
    e$n, e$or, "odds ratio (reminded vs not)", e$p, e$or_ci,
    sprintf("%.0f%% of reminded promises were kept vs %.0f%% without a reminder (%+.0f pp, CI %+.0f to %+.0f). OR %.2f.", 100 * e$rate1, 100 * e$rate0, 100 * e$rd, 100 * e$rd_ci[1], 100 * e$rd_ci[2], e$or),
    "Reminders were sent at random within strategy (a simulated trial); in a real book reminder assignment would be confounded with who the agent thought needed one.")
  for (s in sort(unique(na.omit(prom$segment_label)))) {
    d <- prom %>% filter(segment_label == s)
    if (sum(d$reminded) < 20 || sum(1 - d$reminded) < 20) next
    e <- binary_effect(d, "completed", "reminded", "debt_id")
    findings[[paste0("B_", s)]] <- finding(paste0("stat_reminder_", gsub("[^a-z0-9]+", "_", tolower(s))), "reminder",
      sprintf("Within \"%s\", does a reminder help promises get kept?", s), "P(completed | reminded) > P(completed | not)",
      "Logistic regression within segment; borrower-clustered bootstrap", e$n, e$or, "odds ratio (reminded vs not)", e$p, e$or_ci,
      sprintf("%.0f%% kept with reminder vs %.0f%% without (%+.0f pp).", 100 * e$rate1, 100 * e$rate0, 100 * e$rd),
      "Smaller sample within segment; interpret alongside the pooled estimate.", segment = s)
  }

  # ---- C. Do the graph communities differ in payment? ----------------------
  nb <- net$node_tbl
  tab <- table(nb$segment_label, nb$paid)
  chi <- suppressWarnings(chisq.test(tab, correct = FALSE))
  v <- cramers_v(tab)
  rng <- nb %>% group_by(segment_label) %>% summarise(r = mean(paid), .groups = "drop")
  findings$C <- finding("stat_segments_differ", "segments", "Do the behavioural communities found by the network differ in whether borrowers pay?",
    "Payment rate is not independent of community", "Chi-square test of independence (community x paid); Cramer's V",
    nrow(nb), v, "Cramer's V", chi$p.value, c(NA, NA),
    sprintf("Payment rates range from %.0f%% (%s) to %.0f%% (%s) across %d communities; chi-square p = %.2g.", 100 * min(rng$r), rng$segment_label[which.min(rng$r)], 100 * max(rng$r), rng$segment_label[which.max(rng$r)], nrow(rng), chi$p.value),
    "The communities were built from contact behaviour only, never from payment, so this is an out-of-feature check that the segments mean something. It says the groups differ, not why.")

  # ---- D. Time to first payment --------------------------------------------
  sv <- nb %>% filter(!is.na(days_to_payment)) %>% mutate(segment_label = factor(segment_label), strategy = factor(strategy, levels = c("standard", "reminder_first", "evening_contact")))
  lr <- survdiff(Surv(days_to_payment, observed) ~ segment_label, data = sv)
  lr_p <- 1 - pchisq(lr$chisq, length(lr$n) - 1)
  km <- survfit(Surv(days_to_payment, observed) ~ segment_label, data = sv)
  med <- summary(km)$table[, "median"]
  findings$D <- finding("stat_time_to_payment_segments", "survival", "How long until a first payment lands, and does it differ by segment?",
    "Survival curves differ across communities", "Kaplan-Meier estimate; log-rank test",
    nrow(sv), lr$chisq, "log-rank chi-square", lr_p, c(NA, NA),
    sprintf("Median days to first payment: %s.", paste(sprintf("%s %s", sub("segment_label=", "", names(med)), ifelse(is.na(med), "not reached", round(med, 1))), collapse = "; ")),
    "Accounts still open at the horizon are censored, not treated as failures; escalated accounts are censored at escalation.")
  cox <- coxph(Surv(days_to_payment, observed) ~ segment_label + strategy + log(amount_due), data = sv)
  cs <- summary(cox)
  for (st in c("reminder_first", "evening_contact")) {
    row <- paste0("strategy", st)
    hr <- cs$conf.int[row, ]; p <- cs$coefficients[row, "Pr(>|z|)"]
    findings[[paste0("D_", st)]] <- finding(paste0("stat_cox_", st), "survival",
      sprintf("Adjusting for segment and balance, does the \"%s\" strategy speed up payment vs standard?", st),
      "Hazard ratio != 1", "Cox proportional hazards (segment + strategy + log balance)", nrow(sv), hr["exp(coef)"], "hazard ratio vs standard", p,
      c(hr["lower .95"], hr["upper .95"]),
      sprintf("HR %.2f (95%% CI %.2f-%.2f): payments arrive %s under %s.", hr["exp(coef)"], hr["lower .95"], hr["upper .95"], ifelse(hr["exp(coef)"] > 1, "faster", "slower"), st),
      "Proportional hazards assumed; strategy was randomised so the adjustment is for precision, not confounding.")
  }

  # ---- E. Strategy comparison (randomised) ---------------------------------
  st <- borrowers %>% mutate(strategy = factor(strategy, levels = c("standard", "reminder_first", "evening_contact")))
  tab <- table(st$strategy, st$paid)
  chi <- suppressWarnings(chisq.test(tab, correct = FALSE))
  findings$E <- finding("stat_strategy_overall", "strategy", "Do the three contact strategies differ in whether borrowers pay?",
    "Payment rate depends on strategy", "Chi-square test (strategy x paid); strategies were randomly assigned",
    nrow(st), cramers_v(tab), "Cramer's V", chi$p.value, c(NA, NA),
    sprintf("Payment rates: %s.", paste(sprintf("%s %.0f%%", levels(st$strategy), 100 * tapply(st$paid, st$strategy, mean)), collapse = ", ")),
    "A simulated randomised assignment. The right next question is which segment each strategy helps, not which is best overall.")
  perf <- st %>% group_by(strategy) %>%
    summarise(n = n(), payment_rate = mean(paid), ci = list(boot_ci(paid)),
              avg_days_to_payment = mean(days_to_payment[observed == 1]), median_days_to_payment = median(days_to_payment[observed == 1]), .groups = "drop") %>%
    mutate(ci_low = map_dbl(ci, 1), ci_high = map_dbl(ci, 2), strategy = as.character(strategy)) %>% select(-ci)
  write_table("strategy_performance", perf)

  # ---- N. The planted null: weekday ---------------------------------------
  tab <- table(attempts$weekday, attempts$answered)
  chi <- suppressWarnings(chisq.test(tab, correct = FALSE))
  findings$N <- finding("stat_weekday_null", "weekday", "Does the day of the week a call is made change whether it is answered?",
    "P(answer) depends on weekday", "Chi-square test of independence (weekday x answered)",
    nrow(attempts), cramers_v(tab), "Cramer's V", chi$p.value, c(NA, NA),
    sprintf("Pick-up rate by weekday ranges %.0f-%.0f%%; chi-square p = %.2f.", 100 * min(tapply(attempts$answered, attempts$weekday, mean)), 100 * max(tapply(attempts$answered, attempts$weekday, mean)), chi$p.value),
    "Included deliberately as a check: with this many attempts, a real weekday effect would be easy to detect. A non-result here is what a well-behaved analysis should produce.")

  # ---- Multiple comparisons -----------------------------------------------
  out <- bind_rows(findings) %>%
    mutate(p_adjusted = p.adjust(p_value, method = "BH"), significant = p_adjusted < 0.05)
  write_table("statistical_findings", out)
  log_step("statistics: %d findings, %d significant after BH; weekday null p=%.2f", nrow(out), sum(out$significant), out$p_value[out$finding_id == "stat_weekday_null"])
  saveRDS(list(findings = out, km = km, cox = cox, attempts = attempts, promises = prom, strategy = perf), file.path(OUTPUT_DIR, "statistics.rds"))
  out
}
