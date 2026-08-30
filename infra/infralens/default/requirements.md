Product: InfraLens Skills Suite (this product).
Target: production Azure, new dedicated resource group (do not reuse EQIP).
Existing: GitHub repo raghavrallan/infralens is mapped. Code is FastAPI API + static Next.js frontend, RQ worker, Postgres, Redis.
Deploy shape: Azure Container Apps for API and worker, static web for frontend, private data plane (Postgres + Redis), Key Vault, Azure Monitor.
Constraints: no silent apply; Terraform via PR; gated Lead+ apply; break-glass off.
Ask: design the production architecture, ADRs, and delivery task chain from scratch for this product.