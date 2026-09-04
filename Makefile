# SettleWise - operational service (Python) + intelligence layer (R).
#
#   make setup         venv + Python deps, R deps via renv
#   make synth         regenerate the synthetic history (seeded)
#   make seed          reset the operational DB (includes the live book)
#   make intelligence  extract live events, run the R pipeline
#   make report        render the Quarto report
#   make test          Python + R tests
#   make run           start the API + dashboard

PY := .venv/bin/python
RSCRIPT := Rscript
QUARTO := $(shell command -v quarto 2>/dev/null || echo $(HOME)/.local/bin/quarto)
SEED ?= 42
N ?= 1000

.PHONY: setup synth seed extract intelligence report test test-py test-r run all

setup:
	python3.11 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
	cd intelligence && $(RSCRIPT) -e 'if (!requireNamespace("renv", quietly=TRUE)) install.packages("renv", repos="https://cloud.r-project.org"); renv::restore(prompt=FALSE)'

synth:
	$(PY) -m server.intelligence.synthetic --seed $(SEED) --n $(N) --live 10

seed:
	$(PY) -m server.seed reset

extract:
	$(PY) -m server.intelligence.extract

intelligence: extract
	cd intelligence && $(RSCRIPT) run_all.R

report:
	cd intelligence && $(QUARTO) render report.qmd

test: test-py test-r

test-py:
	$(PY) -m pytest tests -q

test-r:
	cd intelligence && $(RSCRIPT) tests/run_tests.R

run:
	.venv/bin/uvicorn server.main:app --port 8787 --reload

# Everything from a clean database to a rendered report.
all: synth seed intelligence report
