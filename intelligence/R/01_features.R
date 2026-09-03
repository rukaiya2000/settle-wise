# Per-borrower feature snapshots from the event log.
#
# featurize() is written so it works on any prefix of a borrower's events,
# because the model needs "what was known before this attempt" and the
# network needs "everything we saw". Same definitions, different cut-offs -
# that is what makes the training features and the live features
# comparable.
#
# The network deliberately uses only *contact behaviour* (did they pick up,
# when, what did they say) and not payment outcomes. That way "do the
# segments differ in payment rate?" is a real out-of-sample question rather
# than the graph being asked to rediscover its own inputs.

featurize <- function(events, borrowers) {
  calls <- events %>% filter(event_type == "call_attempt")
  answered <- calls %>% filter(outcome != "no_answer")

  by_call <- calls %>%
    group_by(debt_id) %>%
    summarise(
      n_calls = n(),
      contact_success_rate = mean(outcome != "no_answer"),
      evening_share = mean(time_bucket == "evening"),
      n_evening = sum(time_bucket == "evening"),
      evening_contact_rate = if (any(time_bucket == "evening")) mean(outcome[time_bucket == "evening"] != "no_answer") else NA_real_,
      daytime_contact_rate = if (any(time_bucket != "evening")) mean(outcome[time_bucket != "evening"] != "no_answer") else NA_real_,
      .groups = "drop"
    )

  by_answered <- answered %>%
    group_by(debt_id) %>%
    summarise(
      n_answered = n(),
      objection_rate = mean(outcome == "answered_objection"),
      refusal_rate = mean(outcome == "answered_refused"),
      promise_rate = mean(outcome == "answered_promised"),
      .groups = "drop"
    )

  # Preferred bucket: highest answer rate, ties broken by attempts.
  pref <- calls %>%
    group_by(debt_id, time_bucket) %>%
    summarise(rate = mean(outcome != "no_answer"), n = n(), .groups = "drop") %>%
    arrange(debt_id, desc(rate), desc(n)) %>%
    group_by(debt_id) %>% slice(1) %>% ungroup() %>%
    select(debt_id, preferred_bucket = time_bucket)

  # Promise completion: a payment landed within 10 days of a promise call.
  promises <- calls %>% filter(outcome == "answered_promised") %>% select(debt_id, promise_time = event_time)
  payments <- events %>% filter(event_type == "payment") %>% select(debt_id, pay_time = event_time, response_time_seconds)
  completion <- promises %>%
    left_join(payments, by = "debt_id", relationship = "many-to-many") %>%
    mutate(within = !is.na(pay_time) & pay_time > promise_time & as.numeric(difftime(as.POSIXct(pay_time), as.POSIXct(promise_time), units = "days")) <= 10) %>%
    group_by(debt_id, promise_time) %>% summarise(completed = any(within), .groups = "drop") %>%
    group_by(debt_id) %>% summarise(n_promises = n(), promise_completion_rate = mean(completed), .groups = "drop")

  sms <- events %>% filter(event_type == "sms") %>%
    group_by(debt_id) %>% summarise(n_reminders = sum(outcome == "reminder_sent"), .groups = "drop")

  resp <- payments %>% group_by(debt_id) %>% summarise(avg_response_time = mean(response_time_seconds, na.rm = TRUE), .groups = "drop")

  span <- events %>% group_by(debt_id) %>%
    summarise(n_events = n(),
              days_active = as.numeric(difftime(max(as.POSIXct(event_time)), min(as.POSIXct(event_time)), units = "days")),
              .groups = "drop")

  borrowers %>%
    select(debt_id, cohort, amount_due) %>%
    left_join(span, by = "debt_id") %>%
    left_join(by_call, by = "debt_id") %>%
    left_join(by_answered, by = "debt_id") %>%
    left_join(pref, by = "debt_id") %>%
    left_join(completion, by = "debt_id") %>%
    left_join(sms, by = "debt_id") %>%
    left_join(resp, by = "debt_id") %>%
    mutate(
      across(c(n_events, n_calls, n_answered, n_evening, n_promises, n_reminders), ~ coalesce(.x, 0L)),
      across(c(contact_success_rate, evening_share, objection_rate, refusal_rate, promise_rate), ~ coalesce(.x, 0)),
      days_active = coalesce(days_active, 0),
      low_history = n_calls < 2,
      feature_version = FEATURE_VERSION
    )
}

# The columns the similarity graph is built on, and how missing values are
# filled (a borrower never called in the evening has no evening rate; use
# their overall rate rather than dropping them).
NETWORK_FEATURES <- c("contact_success_rate", "daytime_contact_rate", "evening_contact_rate", "evening_lift",
                      "objection_rate", "refusal_rate", "promise_rate", "log_calls")

network_matrix <- function(features, center = NULL, scale = NULL) {
  m <- features %>%
    mutate(
      daytime_contact_rate = coalesce(daytime_contact_rate, contact_success_rate),
      evening_contact_rate = coalesce(evening_contact_rate, contact_success_rate),
      evening_lift = evening_contact_rate - daytime_contact_rate,
      log_calls = log1p(n_calls)
    ) %>%
    select(all_of(NETWORK_FEATURES)) %>%
    as.matrix()
  rownames(m) <- features$debt_id
  if (is.null(center)) { center <- colMeans(m); scale <- apply(m, 2, sd); scale[scale == 0] <- 1 }
  z <- sweep(sweep(m, 2, center, "-"), 2, scale, "/")
  attr(z, "center") <- center; attr(z, "scale") <- scale
  z
}

cosine_similarity <- function(a, b = a) {
  an <- a / pmax(sqrt(rowSums(a^2)), 1e-9)
  bn <- b / pmax(sqrt(rowSums(b^2)), 1e-9)
  an %*% t(bn)
}

run_features <- function() {
  log_step("features: reading events")
  events <- read_table("interaction_events")
  borrowers <- read_table("intel_borrowers")
  feats <- featurize(events, borrowers)
  write_table("borrower_features", feats %>% select(
    debt_id, cohort, n_events, n_calls, contact_success_rate, promise_completion_rate, objection_rate,
    evening_share, evening_contact_rate, daytime_contact_rate, avg_response_time, preferred_bucket,
    n_reminders, days_active, amount_due, low_history, feature_version))
  log_step("features: %d borrowers (%d historical, %d live)", nrow(feats), sum(feats$cohort == "historical"), sum(feats$cohort == "live"))
  list(events = events, borrowers = borrowers, features = feats)
}
