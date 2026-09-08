# Disabled clients

The registry loads `config/*.yaml` only — configs in this directory are not loaded,
so these clients do not appear on the landing page and their `/api/c/<id>/…` routes
404. The demo ships GCP Platform Support alone.

To re-enable one, move its YAML back up to `config/` and restart the API.
Their corpora, prompts, assets, evals and tools all remain in the repo untouched;
the live-API tests in `apps/api/tests/test_e2e_citations.py` (opt-in via
`RUN_INTEGRATION=1`) assume Acme and Meridian are enabled.
