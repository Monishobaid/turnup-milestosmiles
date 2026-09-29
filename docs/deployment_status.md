# TURNUP Team 09 deployment status

As of 2026-09-29, the presentation dashboard is deployed on `vm-hack-team09` in Azure region `swedencentral`.

Presentation URL:

```text
https://4.225.218.235:8000/turnup/
```

The URL is routed through the VM's existing JupyterHub HTTPS proxy. The certificate is the VM's existing certificate, so a browser may show a certificate warning for the IP address. The dashboard is read-only and uses the audited/model-scored data packaged under `web/data/processed/`.

Current safety state:

- Dashboard: live.
- Optimiser/API code: deployed but not publicly exposed.
- Workload dispatch: dry-run only.
- Official forecast feed: not configured; no provider token was invented.
- Site/grid mapping: demo placeholder only; replace it before locational claims.
- Key Vault: the signed-in account can read the vault but was denied `secrets set` permission, so a secret-manager token could not be created automatically.

Required administrator actions before production activation:

1. Provide or approve the EirGrid/provider forecast endpoint and token policy.
2. Grant the deployment identity Key Vault secret-set/read access, or add the secrets through the portal.
3. Confirm the actual site/grid node and constraint region.
4. Provide the approved Kubernetes, Azure Batch or Slurm dispatch endpoint and credentials.
5. Keep `TURNUP_DISPATCH_MODE=dry-run` until workload owners approve live execution.
