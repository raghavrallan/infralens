# Bugs

The shared Redis read that showed one resource's detail on every dropdown choice is fixed. Layout, catalog, SQL allow lists, and container revisions each keep their own key.

Still open:

- `engine/app/providers/azure_infra.py` reads Azure over HTTP. Those chat reads do not appear in the sandbox audit.
- The root `Dockerfile` copies `frontend/` during the image build. That directory is not in this repo, so `docker build` of that image fails. `scripts/start-suite.sh` does not need it.
- Service activity is the last 7 days of administrative events. A service with no changes in that window shows an empty activity tab. Key Vault, Logic Apps, and Cognitive Services can be in that state even when the resources exist.
- Cost Management can return 429. A failed sync keeps the previous snapshot. Do not start a full cost sync to refresh facts or activity.
