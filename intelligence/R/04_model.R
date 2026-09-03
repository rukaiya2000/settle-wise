# One prediction task, done carefully:
#   "Will a payment land within 7 days of this call attempt?"
#
# Rows are call attempts. Every feature is computed from events strictly
# before the attempt (running counts), so nothing from the outcome leaks
# into the inputs. The graph contributes two features the same way it
# does for a live borrower: the attempt's as-of behaviour vector is
# matched to its nearest training borrowers and their payment rate and
# contact rate come along. That keeps training and serving identical.
#
# Split is chronological at the borrower level (by account open date):
# train on the earliest 60% of accounts, tune on the next 20%, report on
# the latest 20%. Three models, in order of complexity: the neighbour
# rate alone (the "historical rate" baseline), a penalised logistic
# regression, and a small gradient-boosted tree. The champion is chosen on
# validation PR-AUC and reported on test - never the other way round.

suppressPackageStartupMessages({
  library(glmnet)
  library(xgboost)
  library(yardstick)
})

MODEL_VERSION <- "payment7d-v1"
LABEL_WINDOW_DAYS <- 7
K_MODEL_NEIGHBOURS <- 20

FEATURE_LABELS <- c(
  prior_contact_rate = "share of earlier calls answered",
  prior_evening_lift = "picks up more in the evening than daytime",
  prior_objection_rate = "affordability objections on earlier calls",
  prior_refusal_rate = "refusals on earlier calls",
  prior_promise_rate = "promises made on earlier calls",
  prior_payments = "payments already made",
  prior_broken_promises = "promises not yet followed by a payment",
  prior_reminders = "reminders sent",
  log_prior_calls = "number of earlier calls",
  days_since_open = "days since the account opened",
  days_since_last_call = "days since the last call",
  is_evening = "this attempt is in the evening",
  log_amount = "size of the balance",
  outstanding_share = "share of the balance still outstanding",
  strategy_reminder_first = "reminder-first strategy",
  strategy_evening_contact = "evening-contact strategy",
  neighbor_paid_rate = "similar borrowers' payment rate",
  neighbor_contact_rate = "similar borrowers' pick-up rate"
)

# Running (as-of) features for every call attempt of every borrower.
attempt_dataset <- function(events, borrowers) {
  ev <- events %>% arrange(debt_id, event_time) %>% mutate(t = as.POSIXct(event_time))
  calls <- ev %>% filter(event_type == "call_attempt")
  pays <- ev %>% filter(event_type == "payment") %>% select(debt_id, pay_t = t)
  # strategy comes from the events themselves (it is stamped on every row).
  opened <- borrowers %>% transmute(debt_id, opened = as.POSIXct(opened_at), amount_due)

  calls %>%
    group_by(debt_id) %>%
    mutate(
      answered = outcome != "no_answer",
      evening = time_bucket == "evening",
      prior_calls = row_number() - 1,
      prior_answered = lag(cumsum(answered), default = 0),
      prior_evening = lag(cumsum(evening), default = 0),
      prior_evening_answered = lag(cumsum(answered & evening), default = 0),
      prior_day = prior_calls - prior_evening,
      prior_day_answered = prior_answered - prior_evening_answered,
      prior_objections = lag(cumsum(outcome == "answered_objection"), default = 0),
      prior_refusals = lag(cumsum(outcome == "answered_refused"), default = 0),
      prior_promises = lag(cumsum(outcome == "answered_promised"), default = 0),
      days_since_last_call = as.numeric(difftime(t, lag(t), units = "days"))
    ) %>%
    ungroup() %>%
    left_join(opened, by = "debt_id") %>%
    mutate(
      days_since_open = as.numeric(difftime(t, opened, units = "days")),
      days_since_last_call = coalesce(days_since_last_call, days_since_open),
      prior_contact_rate = if_else(prior_calls > 0, prior_answered / prior_calls, NA_real_),
      prior_evening_rate = if_else(prior_evening > 0, prior_evening_answered / prior_evening, NA_real_),
      prior_day_rate = if_else(prior_day > 0, prior_day_answered / prior_day, NA_real_),
      prior_objection_rate = if_else(prior_answered > 0, prior_objections / prior_answered, 0),
      prior_refusal_rate = if_else(prior_answered > 0, prior_refusals / prior_answered, 0),
      prior_promise_rate = if_else(prior_answered > 0, prior_promises / prior_answered, 0),
      log_prior_calls = log1p(prior_calls),
      is_evening = as.integer(evening),
      log_amount = log(amount_due),
      outstanding_share = amount_due_at_event / amount_due,
      strategy_reminder_first = as.integer(strategy == "reminder_first"),
      strategy_evening_contact = as.integer(strategy == "evening_contact")
    ) %>%
    # Prior payments / reminders / broken promises as counts before t.
    left_join(ev %>% filter(event_type == "payment") %>% group_by(debt_id) %>% summarise(pay_times = list(t), .groups = "drop"), by = "debt_id") %>%
    left_join(ev %>% filter(outcome == "reminder_sent") %>% group_by(debt_id) %>% summarise(rem_times = list(t), .groups = "drop"), by = "debt_id") %>%
    mutate(
      prior_payments = map2_int(pay_times, t, ~ sum(.x < .y)),
      prior_reminders = map2_int(rem_times, t, ~ sum(.x < .y)),
      prior_broken_promises = pmax(prior_promises - prior_payments, 0),
      label = map2_int(pay_times, t, ~ as.integer(any(.x > .y & .x <= .y + LABEL_WINDOW_DAYS * 86400)))
    ) %>%
    select(-pay_times, -rem_times)
}

# The as-of behaviour vector in the network's feature space, so an attempt
# (or a live borrower) can be matched against the historical graph.
asof_network_matrix <- function(d, ref) {
  m <- d %>% transmute(
    contact_success_rate = coalesce(prior_contact_rate, ref$mean_contact),
    daytime_contact_rate = coalesce(prior_day_rate, contact_success_rate),
    evening_contact_rate = coalesce(prior_evening_rate, contact_success_rate),
    evening_lift = evening_contact_rate - daytime_contact_rate,
    objection_rate = prior_objection_rate, refusal_rate = prior_refusal_rate, promise_rate = prior_promise_rate,
    log_calls = log_prior_calls
  ) %>% select(all_of(NETWORK_FEATURES)) %>% as.matrix()
  sweep(sweep(m, 2, ref$center, "-"), 2, ref$scale, "/")
}

neighbour_features <- function(Zq, Zref, paid_ref, contact_ref, exclude_self = NULL) {
  S <- cosine_similarity(Zq, Zref)
  if (!is.null(exclude_self)) S[cbind(seq_len(nrow(S)), match(exclude_self, rownames(Zref)))] <- -Inf
  S[is.na(S)] <- -Inf
  nn <- t(apply(S, 1, function(r) order(r, decreasing = TRUE)[1:K_MODEL_NEIGHBOURS]))
  tibble(neighbor_paid_rate = rowMeans(matrix(paid_ref[nn], nrow = nrow(nn))),
         neighbor_contact_rate = rowMeans(matrix(contact_ref[nn], nrow = nrow(nn))))
}

MODEL_FEATURES <- names(FEATURE_LABELS)

design <- function(d) {
  m <- d %>% mutate(prior_contact_rate = coalesce(prior_contact_rate, 0), prior_evening_lift = coalesce(prior_evening_rate, prior_contact_rate) - coalesce(prior_day_rate, prior_contact_rate)) %>%
    select(all_of(MODEL_FEATURES)) %>% as.matrix()
  m[is.na(m)] <- 0
  m
}

metrics_at <- function(y, p, threshold) {
  truth <- factor(y, levels = c(1, 0))
  est <- factor(as.integer(p >= threshold), levels = c(1, 0))
  tibble(
    roc_auc = roc_auc_vec(truth, p), pr_auc = pr_auc_vec(truth, p), brier = mean((p - y)^2),
    precision_at_threshold = precision_vec(truth, est), recall_at_threshold = recall_vec(truth, est),
    f1_at_threshold = f_meas_vec(truth, est), threshold = threshold, positive_rate = mean(y)
  )
}

best_threshold <- function(y, p) {
  grid <- seq(0.05, 0.95, by = 0.01)
  f1 <- sapply(grid, function(th) { est <- factor(as.integer(p >= th), levels = c(1, 0)); f_meas_vec(factor(y, levels = c(1, 0)), est) })
  grid[which.max(replace(f1, is.na(f1), -1))]
}

calibration_bins <- function(y, p, bins = 10) {
  q <- unique(quantile(p, probs = seq(0, 1, length.out = bins + 1)))
  b <- cut(p, q, include.lowest = TRUE)
  tibble(bin = as.integer(b), mean_pred = tapply(p, b, mean), observed = tapply(y, b, mean), n = as.integer(table(b))) %>%
    filter(!is.na(bin)) %>% distinct(bin, .keep_all = TRUE)
}

run_model <- function(ctx, net) {
  log_step("model: building attempt-level dataset")
  hist_b <- ctx$borrowers %>% filter(cohort == "historical")
  d <- attempt_dataset(ctx$events %>% filter(cohort == "historical"), hist_b)

  # Chronological split by account open date.
  cuts <- quantile(as.POSIXct(hist_b$opened_at), c(0.6, 0.8))
  split_of <- hist_b %>% transmute(debt_id, split = case_when(as.POSIXct(opened_at) <= cuts[1] ~ "train", as.POSIXct(opened_at) <= cuts[2] ~ "valid", TRUE ~ "test"))
  d <- d %>% left_join(split_of, by = "debt_id")

  # Reference cohort for neighbour features = training borrowers' full
  # histories (the graph's own feature space, standardised the same way).
  Zall <- net$Z
  train_ids <- split_of$debt_id[split_of$split == "train"]
  Zref <- Zall[rownames(Zall) %in% train_ids, , drop = FALSE]
  ref <- list(center = attr(Zall, "center"), scale = attr(Zall, "scale"),
              mean_contact = mean(ctx$features$contact_success_rate[ctx$features$debt_id %in% train_ids]))
  paid_ref <- hist_b$paid[match(rownames(Zref), hist_b$debt_id)]
  contact_ref <- ctx$features$contact_success_rate[match(rownames(Zref), ctx$features$debt_id)]
  nf <- neighbour_features(asof_network_matrix(d, ref), Zref, paid_ref, contact_ref, exclude_self = d$debt_id)
  d <- bind_cols(d, nf)

  tr <- d %>% filter(split == "train"); va <- d %>% filter(split == "valid"); te <- d %>% filter(split == "test")
  Xtr <- design(tr); Xva <- design(va); Xte <- design(te)
  log_step("model: %d train / %d valid / %d test attempts; positive rate %.2f", nrow(tr), nrow(va), nrow(te), mean(tr$label))

  registry <- list(); preds_test <- list()

  # 1. Historical-rate baseline: the neighbour payment rate as the score.
  th <- best_threshold(va$label, va$neighbor_paid_rate)
  registry$baseline <- metrics_at(te$label, te$neighbor_paid_rate, th) %>% mutate(model_version = paste0(MODEL_VERSION, "-baseline"), model_name = "Similar-borrower rate (baseline)", notes = "Score = payment rate of the 20 most similar training borrowers. No fitting.")
  va_pr <- c(baseline = pr_auc_vec(factor(va$label, levels = c(1, 0)), va$neighbor_paid_rate))
  preds_test$baseline <- te$neighbor_paid_rate

  # 2. Penalised logistic regression.
  set.seed(SEED)
  cvfit <- cv.glmnet(Xtr, tr$label, family = "binomial", alpha = 0.5, nfolds = 5)
  p_va <- as.numeric(predict(cvfit, Xva, s = "lambda.min", type = "response"))
  p_te <- as.numeric(predict(cvfit, Xte, s = "lambda.min", type = "response"))
  th <- best_threshold(va$label, p_va)
  registry$glmnet <- metrics_at(te$label, p_te, th) %>% mutate(model_version = paste0(MODEL_VERSION, "-glmnet"), model_name = "Elastic-net logistic regression", notes = sprintf("alpha=0.5, lambda.min=%.4g by 5-fold CV on training accounts.", cvfit$lambda.min))
  va_pr["glmnet"] <- pr_auc_vec(factor(va$label, levels = c(1, 0)), p_va)
  preds_test$glmnet <- p_te

  # 3. Gradient boosting, shallow, early-stopped on validation.
  set.seed(SEED)
  dtr <- xgb.DMatrix(Xtr, label = tr$label); dva <- xgb.DMatrix(Xva, label = va$label)
  bst <- xgb.train(params = list(objective = "binary:logistic", eval_metric = "aucpr", max_depth = 3, eta = 0.05, subsample = 0.8, colsample_bytree = 0.8, min_child_weight = 5),
                   data = dtr, nrounds = 600, watchlist = list(valid = dva), early_stopping_rounds = 40, verbose = 0)
  p_va <- predict(bst, Xva); p_te <- predict(bst, Xte)
  th <- best_threshold(va$label, p_va)
  registry$xgb <- metrics_at(te$label, p_te, th) %>% mutate(model_version = paste0(MODEL_VERSION, "-xgboost"), model_name = "Gradient-boosted trees", notes = sprintf("depth 3, eta 0.05, %d rounds (early-stopped on validation PR-AUC).", bst$best_iteration))
  va_pr["xgb"] <- pr_auc_vec(factor(va$label, levels = c(1, 0)), p_va)
  preds_test$xgb <- p_te

  champion <- names(which.max(va_pr[c("glmnet", "xgb")]))
  reg <- bind_rows(registry) %>%
    mutate(trained_at = NOW, n_train = nrow(tr), n_test = nrow(te), feature_version = FEATURE_VERSION,
           is_champion = model_version == paste0(MODEL_VERSION, "-", ifelse(champion == "xgb", "xgboost", champion)),
           calibration_json = map_chr(c("baseline", "glmnet", "xgb"), ~ toJSON(calibration_bins(te$label, preds_test[[.x]]), digits = 4)))
  write_table("model_registry", reg %>% select(model_version, model_name, trained_at, n_train, n_test, roc_auc, pr_auc, brier,
                                               precision_at_threshold, recall_at_threshold, f1_at_threshold, threshold, positive_rate,
                                               calibration_json, feature_version, is_champion, notes))
  log_step("model: champion = %s (valid PR-AUC %.3f); test ROC-AUC %.3f, PR-AUC %.3f, Brier %.3f",
           champion, va_pr[champion], reg$roc_auc[reg$is_champion], reg$pr_auc[reg$is_champion], reg$brier[reg$is_champion])

  # ---- Predictions for live borrowers -------------------------------------
  # Their "next attempt" is scored at the segment's best bucket with their
  # own strategy; everything else is their history as of now.
  live_b <- ctx$borrowers %>% filter(cohort == "live")
  live_ev <- ctx$events %>% filter(cohort == "live")
  now_t <- max(as.POSIXct(c(live_ev$event_time, ctx$events$event_time)))
  seg_bucket <- net$segments %>% left_join(net$profiles %>% select(community, best_bucket), by = "community") %>% select(debt_id, best_bucket)
  live_rows <- map_dfr(live_b$debt_id, function(id) {
    e <- live_ev %>% filter(debt_id == id)
    b <- live_b %>% filter(debt_id == id)
    # Append a pseudo-attempt at "now" and take its as-of row.
    bucket <- coalesce(seg_bucket$best_bucket[seg_bucket$debt_id == id][1], "afternoon")
    pseudo <- tibble(event_id = "pseudo", debt_id = id, cohort = "live", event_time = format(now_t + 3600, "%Y-%m-%dT%H:%M:%S"),
                     event_type = "call_attempt", channel = "voice", hour = ifelse(bucket == "evening", 18L, 14L), time_bucket = bucket,
                     weekday = 0L, outcome = "no_answer", strategy = b$strategy, amount_due_at_event = b$amount_due * (1 - 0), amount_offered = NA_real_,
                     amount_paid = NA_real_, response_time_seconds = NA_real_, metadata_json = "{}")
    paid_so_far <- sum(e$amount_paid, na.rm = TRUE)
    pseudo$amount_due_at_event <- b$amount_due - paid_so_far
    attempt_dataset(bind_rows(e, pseudo), b) %>% filter(event_id == "pseudo")
  })
  if (nrow(live_rows)) {
    nf <- neighbour_features(asof_network_matrix(live_rows, ref), Zref, paid_ref, contact_ref)
    live_rows <- bind_cols(live_rows, nf)
    Xl <- design(live_rows)
    if (champion == "xgb") {
      p <- predict(bst, Xl)
      contrib <- predict(bst, Xl, predcontrib = TRUE)[, MODEL_FEATURES, drop = FALSE]
    } else {
      p <- as.numeric(predict(cvfit, Xl, s = "lambda.min", type = "response"))
      beta <- as.numeric(coef(cvfit, s = "lambda.min"))[-1]
      contrib <- sweep(Xl, 2, colMeans(Xtr), "-") %*% diag(beta); colnames(contrib) <- MODEL_FEATURES
    }
    explain <- map(seq_len(nrow(Xl)), function(i) {
      c <- contrib[i, ]; top <- order(abs(c), decreasing = TRUE)[1:3]
      lapply(top, function(j) list(feature = MODEL_FEATURES[j], label = unname(FEATURE_LABELS[MODEL_FEATURES[j]]), contribution = unname(round(c[j], 3)), direction = ifelse(c[j] >= 0, "up", "down")))
    })
    preds <- tibble(prediction_id = paste0("pred_", live_rows$debt_id, "_", format(Sys.time(), "%Y%m%d%H%M%S")), debt_id = live_rows$debt_id,
                    prediction_type = "payment_after_next_contact", prediction_value = round(p, 4),
                    model_version = reg$model_version[reg$is_champion], generated_at = NOW, feature_version = FEATURE_VERSION,
                    explanation_json = map_chr(explain, ~ toJSON(.x, auto_unbox = TRUE)))
    write_table("predictions", preds)
    log_step("model: scored %d live borrowers", nrow(preds))
  }
  saveRDS(list(registry = reg, champion = champion, test = te %>% mutate(p_glmnet = preds_test$glmnet, p_xgb = preds_test$xgb, p_baseline = preds_test$baseline),
               glmnet = cvfit, xgb = bst, features = MODEL_FEATURES, valid_pr = va_pr), file.path(OUTPUT_DIR, "model.rds"))
  reg
}
