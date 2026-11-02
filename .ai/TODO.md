# Todo

- Unify the organization `il_session` login and the agentic engine JWT.
- Move chat Azure reads in `engine/app/providers/azure_infra.py` onto the sandbox CLI so they show up in the sandbox audit.
- The root `Dockerfile` still builds a `frontend/` stage this repo does not contain. Local runs use `scripts/start-suite.sh`. Fix that image before relying on it.
- Add invoice download for billing accounts that grant Billing Reader.
- Page Databricks usage through the Databricks API when Cost Management quantity is not enough.
- Let a project admin invite members without making them an organization admin.
- Activity on service pages is the last 7 days. It does not follow the 30-day or quarter cost range.
