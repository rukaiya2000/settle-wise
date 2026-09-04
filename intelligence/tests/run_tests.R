#!/usr/bin/env Rscript
# Lightweight assertion-based test runner - no testthat dependency, matching
# the rest of this codebase's preference for plain, direct code over adding
# a framework for a handful of checks. Run from intelligence/:
#
#   cd intelligence && Rscript tests/run_tests.R
#
# Targets the pure, DB-free helper functions (statistics, percolation, the
# model's leakage-boundary snapshot) - the run_*() pipeline stages that read
# data/settlewise.db are exercised by `make intelligence` itself and the
# evaluation-vs-ground-truth check in 05_evaluation.R, not here.

for (f in sort(list.files("R", full.names = TRUE))) source(f)

.pass <- 0L
.fail <- 0L

check <- function(name, cond) {
  ok <- isTRUE(cond)
  if (ok) {
    .pass <<- .pass + 1L
    cat(sprintf("  ok   %s\n", name))
  } else {
    .fail <<- .fail + 1L
    cat(sprintf("  FAIL %s\n", name))
  }
}

close_to <- function(a, b, tol = 1e-6) abs(a - b) < tol

# ---- scenarios: odds lift / effect draws -----------------------------------

check("lift_odds: OR of 1 leaves the probability unchanged", close_to(lift_odds(0.3, 1), 0.3))
check("lift_odds: OR of 3 on p=0.5 gives 0.75", close_to(lift_odds(0.5, 3), 0.75))
check("lift_odds: never leaves [0,1]", all(lift_odds(c(0, 0.5, 1), 1e6) <= 1 & lift_odds(c(0, 0.5, 1), 1e-6) >= 0))
set.seed(1); d <- draw_or(2, 1.5, 2.67, 4000)
check("draw_or: draws centre on the point estimate", close_to(median(d), 2, tol = 0.1))
check("draw_or: about 95% of draws fall inside the CI", abs(mean(d > 1.5 & d < 2.67) - 0.95) < 0.02)
check("draw_or: a missing CI yields no effect, not an error", all(draw_or(2, NA, NA, 5) == 1))

# ---- boot_ci: bootstrap CI for a mean --------------------------------------

set.seed(1)
x <- rnorm(500, mean = 10, sd = 2)
ci <- boot_ci(x, R = 300, seed = 1)
check("boot_ci: lower bound below the sample mean", ci[1] < mean(x))
check("boot_ci: upper bound above the sample mean", ci[2] > mean(x))
check("boot_ci: same seed reproduces the same interval", identical(boot_ci(x, R = 300, seed = 1), ci))
check("boot_ci: empty input returns NA, not an error", all(is.na(boot_ci(numeric(0)))))

# Cluster bootstrap: resampling by cluster should widen the interval
# relative to a naive per-row bootstrap when rows within a cluster are
# perfectly correlated (10 clusters of 20 identical values each) - the
# whole reason 00_setup.R resamples by borrower instead of by row.
clustered_x <- rep(rnorm(10, mean = 5), each = 20)
cluster_id <- rep(1:10, each = 20)
ci_naive <- boot_ci(clustered_x, R = 300, seed = 1)
ci_clustered <- boot_ci(clustered_x, cluster = cluster_id, R = 300, seed = 1)
check(
  "boot_ci: cluster resampling gives a wider interval than naive on clustered data",
  (ci_clustered[2] - ci_clustered[1]) > (ci_naive[2] - ci_naive[1])
)

# ---- cramers_v: association strength ---------------------------------------

independent_tab <- matrix(c(50, 50, 50, 50), nrow = 2)
check("cramers_v: independent table gives ~0", close_to(cramers_v(independent_tab), 0, tol = 1e-9))

perfect_tab <- matrix(c(100, 0, 0, 100), nrow = 2)
check("cramers_v: perfectly associated table gives 1", close_to(cramers_v(perfect_tab), 1))

# ---- percolation: lcc_fraction / auc ---------------------------------------

# A single connected component of 10 nodes. Named, matching how the real
# pipeline always uses this function (debt_id-named vertices from
# 02_network.R) - delete_vertices() needs V(g)$name set to resolve
# character ids at all.
g <- make_ring(10)
V(g)$name <- as.character(seq_len(vcount(g)))
check("lcc_fraction: nothing removed -> whole graph connected", lcc_fraction(g, character(0), 10) == 1)
check("lcc_fraction: every node removed -> 0", lcc_fraction(g, V(g)$name, 10) == 0)

# Two disjoint 5-node rings sharing one bridge node removed should leave
# the largest remaining piece at 5/11, not the full 11.
g2 <- disjoint_union(make_ring(5), make_ring(5))
g2 <- add_edges(g2, c(1, 6))  # bridge between the two rings
V(g2)$name <- as.character(seq_len(vcount(g2)))
check(
  "lcc_fraction: removing a bridge node splits the graph as expected",
  close_to(lcc_fraction(g2, "1", 10), 5 / 10)
)

check("auc: straight line y=x from 0 to 1 has AUC 0.5", close_to(auc(c(0, 1), c(0, 1)), 0.5))
check("auc: constant y=1 has AUC 1", close_to(auc(c(0, 0.5, 1), c(1, 1, 1)), 1))

# ---- snapshot_at: the model's leakage-boundary fix -------------------------

events <- tibble(
  debt_id = c("a", "a", "a", "b", "b"),
  event_time = c("2026-01-01T00:00:00", "2026-01-10T00:00:00", "2026-01-20T00:00:00", "2026-01-05T00:00:00", "2026-01-25T00:00:00"),
  event_type = c("call_attempt", "call_attempt", "payment", "call_attempt", "payment"),
  outcome = c("no_answer", "answered_paid", NA, "no_answer", NA)
)
borrowers <- tibble(debt_id = c("a", "b"))

snap_early <- snapshot_at(events, borrowers, as.POSIXct("2026-01-12"))
snap_late <- snapshot_at(events, borrowers, as.POSIXct("2026-02-01"))

check(
  "snapshot_at: borrower 'a' not yet paid as of a cutoff before their payment event",
  isFALSE(snap_early$paid_by_cutoff[snap_early$debt_id == "a"])
)
check(
  "snapshot_at: borrower 'a' IS paid once the cutoff moves past their payment event",
  isTRUE(snap_late$paid_by_cutoff[snap_late$debt_id == "a"])
)
check(
  "snapshot_at: contact rate only counts calls at/before the cutoff (1 of 2 answered, not the later payment)",
  close_to(snap_early$contact_success_rate[snap_early$debt_id == "a"], 0.5)
)
check(
  "snapshot_at: a borrower with zero calls before the cutoff gets 0, not NA",
  close_to(snap_early$contact_success_rate[snap_early$debt_id == "b"], 0)
)

# -----------------------------------------------------------------------------

cat(sprintf("\n%d passed, %d failed\n", .pass, .fail))
if (.fail > 0) quit(status = 1)
