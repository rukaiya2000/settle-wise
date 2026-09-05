# Did the analysis recover what was planted, and only what was planted?
#
# This is the one stage allowed to read data/synthetic/ground_truth.json.
# It writes intelligence/output/evaluation.json, which the report and the
# R tests read. Each check is phrased so that a "FALSE" is a real problem:
# a planted effect the statistics missed, or a null the statistics
# "found".

run_evaluation <- function(ctx, net) {
  log_step("evaluation: comparing against hidden ground truth")
  truth_path <- file.path(SYNTH_DIR, "ground_truth.json")
  if (!file.exists(truth_path)) { log_step("evaluation: no ground truth file; skipping"); return(invisible(NULL)) }
  truth <- fromJSON(truth_path)
  findings <- read_table("statistical_findings")
  metrics <- read_table("network_metrics")
  registry <- read_table("model_registry")
  # model_registry accumulates a row per model per run (append_table), so a
  # second `make intelligence` - or the dashboard's Rebuild button - leaves
  # several rows per model. Compare the latest run only; a multi-row champion
  # made isTRUE(champion$pr_auc > baseline$pr_auc) FALSE and reported 5/6.
  registry <- registry %>% filter(trained_at == max(trained_at))
  segs <- net$node_tbl %>% mutate(truth = unlist(truth$segments[debt_id]))

  # How pure is each discovered community, and which planted segment does
  # it mostly contain? (A confusion table, in words.)
  purity <- segs %>% count(segment_label, truth) %>% group_by(segment_label) %>%
    mutate(share = n / sum(n)) %>% slice_max(share, n = 1) %>% ungroup() %>%
    transmute(community = segment_label, mostly = truth, purity = round(share, 3), n = n)

  # Planted contact-time effect: the discovered community that is mostly
  # "delayed_responsive" should show a significant evening effect; the one
  # that is mostly "prompt_payer" should show a much smaller one.
  ct <- findings %>% filter(analysis_name == "contact_time", !is.na(segment_label)) %>%
    left_join(purity, by = c("segment_label" = "community"))
  delayed_row <- ct %>% filter(mostly == "delayed_responsive") %>% slice_max(n, n = 1)
  prompt_row <- ct %>% filter(mostly == "prompt_payer") %>% slice_max(n, n = 1)

  z <- (metrics$modularity - metrics$null_modularity_mean) / metrics$null_modularity_sd
  champion <- registry %>% filter(is_champion == 1)
  baseline <- registry %>% filter(grepl("baseline", model_version))

  checks <- list(
    ari_vs_truth = metrics$ari_vs_truth,
    n_communities = metrics$n_communities,
    modularity = metrics$modularity,
    modularity_null_z = z,
    modularity_beats_null = isTRUE(z > 3),
    community_purity = purity,
    evening_effect_found_in_delayed = isTRUE(nrow(delayed_row) > 0 && delayed_row$significant == 1 && delayed_row$effect_size > 1.5),
    evening_effect_or_delayed = if (nrow(delayed_row)) delayed_row$effect_size else NA,
    evening_effect_or_prompt = if (nrow(prompt_row)) prompt_row$effect_size else NA,
    reminder_effect_found = isTRUE(findings$significant[findings$finding_id == "stat_reminder_all"] == 1),
    segments_differ_in_payment = isTRUE(findings$significant[findings$finding_id == "stat_segments_differ"] == 1),
    weekday_null_stayed_null = isTRUE(findings$significant[findings$finding_id == "stat_weekday_null"] == 0),
    weekday_null_p = findings$p_value[findings$finding_id == "stat_weekday_null"],
    champion_model = champion$model_name,
    champion_test_roc_auc = champion$roc_auc,
    champion_test_pr_auc = champion$pr_auc,
    baseline_test_pr_auc = baseline$pr_auc,
    model_beats_baseline = isTRUE(champion$pr_auc > baseline$pr_auc),
    evaluated_at = NOW
  )
  write_json(checks, file.path(OUTPUT_DIR, "evaluation.json"), auto_unbox = TRUE, pretty = TRUE, digits = 4)
  pass <- c(checks$modularity_beats_null, checks$evening_effect_found_in_delayed, checks$reminder_effect_found,
            checks$segments_differ_in_payment, checks$weekday_null_stayed_null, checks$model_beats_baseline)
  log_step("evaluation: %d/%d checks pass (ARI %.2f, modularity z=%.1f, weekday p=%.2f, champion PR-AUC %.3f vs baseline %.3f)",
           sum(pass), length(pass), checks$ari_vs_truth, z, checks$weekday_null_p, champion$pr_auc, baseline$pr_auc)
  invisible(checks)
}
