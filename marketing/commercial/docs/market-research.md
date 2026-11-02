# Market research brief

Audience: people who run an Azure estate for a client organization — owners, admins, billing readers, and operators.

## Selected problems

1. Cloud spend is hard to manage because the estate is split across tools and subscriptions.
2. A recommendation does not become a checked change. Someone still has to confirm the resource, decide, and leave a record. Acting on a subscription that is not the project's is a separate failure.

These match Infralens: project-scoped snapshots, Advisor plus alerts plus findings, a playbook, chat, and an approval that records a decision without executing it.

## Evidence

Flexera, *2025 State of the Cloud Report* (14th edition; press release 19 March 2025; more than 750 respondents):

- 84% of respondents said managing cloud spend is the top cloud challenge.
- Respondents estimate that 27% of IaaS/PaaS spend is wasted.
- The press note also says cloud spend is expected to rise and that many organizations exceed budget. Those extra figures are not used in the film.

Sources:

- https://www.flexera.com/about-us/press-center/new-flexera-report-finds-84-percent-of-organizations-struggle-to-manage-cloud-spend
- https://resources.flexera.com/web/pdf/Flexera-State-of-the-Cloud-Report-2025.pdf
- CIO Dive summary of the 27% waste estimate: https://www.ciodive.com/news/cloud-spend-finops-repatriation-generative-ai-flexera/742886/

## Interpretation

Waste persists when cost, inventory, and Advisor are separate, and when nobody confirms that a resource is actually idle before a resize or a stop. That is a reading of the report's own drivers (idle resources, oversized instances, weak visibility), not a claim that Infralens measured them.

## Not claimed

No Infralens customer count, no ROI, no "saves 27%", no comparison that names a competitor as worse, and no statement that the product changes Azure by itself.
