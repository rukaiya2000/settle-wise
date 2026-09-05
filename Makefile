# SettleWise - operational service (Python) + intelligence layer (R).
#
#   make setup         venv + Python deps, R deps via renv
#   make synth         regenerate the synthetic history (seeded)
#   make seed          reset the operational DB (includes the live book)
#   make intelligence  extract live events, run the R pipeline
#   make report        render the Quarto report
#   make test          Python + R tests
#   make run           start the API + dashboard

# The local pipeline always runs on the SQLite file. With DATABASE_URL set in
# .env (for the deployment), `make extract` would otherwise write to Postgres
# while R reads SQLite. scripts/sync_intelligence.py is the one path to
# Postgres, and it reads DATABASE_URL on purpose.
PY := DATABASE_URL= .venv/bin/python
RSCRIPT := Rscript
QUARTO := $(shell command -v quarto 2>/dev/null || echo $(HOME)/.local/bin/quarto)
SEED ?= 42
N ?= 1000

.PHONY: setup synth seed extract intelligence report test test-py test-r run all

setup:
	python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
	cd intelligence && $(RSCRIPT) -e 'if (!requireNamespace("renv", quietly=TRUE)) install.packages("renv", repos="https://cloud.r-project.org"); renv::restore(prompt=FALSE)'

synth:
	$(PY) -m server.intelligence.synthetic --seed $(SEED) --n $(N) --live 10

seed:
	$(PY) -m server.seed reset

extract:
	$(PY) -m server.intelligence.extract

intelligence: extract
	cd intelligence && $(RSCRIPT) run_all.R

# Rendered into dashboard/ so the deployed site serves it at /dashboard/report.html;
# the HTML is committed because the deployment has no R.
report:
	cd intelligence && $(QUARTO) render report.qmd --output report.html && mv report.html ../dashboard/report.html

test: test-py test-r

test-py:
	$(PY) -m pytest tests -q

test-r:
	cd intelligence && $(RSCRIPT) tests/run_tests.R

run:
	.venv/bin/uvicorn server.main:app --port 8787 --reload

# Everything from a clean database to a rendered report.
all: synth seed intelligence report
