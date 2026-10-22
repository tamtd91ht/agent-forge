---
name: deploy-prod
description: Deploy the service to staging with the release script, then verify
---

# Deploy (production)

Same as deploy, but run `scripts/release.sh prod` and page the on-call if the health check fails.
