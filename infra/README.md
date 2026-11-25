# Azure operations

## Apply temporary Blob retention

The application attempts immediate deletion of each staged video. Configure Azure Storage lifecycle management as a backstop for interrupted processes and transient deletion failures.

From Azure CLI, after substituting the storage account and resource group:

```bash
az storage account management-policy create \
  --account-name <storage-account> \
  --resource-group <resource-group> \
  --policy @infra/blob-lifecycle-policy.json
```

The policy deletes block blobs under `compilancestorage/videos/` after one day. The prefix is configured for the project container `compilancestorage`. Change it if `AZURE_STORAGE_CONTAINER_NAME` differs. Review account-wide lifecycle policies first because this command replaces the storage account's management policy document.

## Secrets

Rotate credentials that were included in the uploaded project archive. Store new values in Azure Key Vault or the deployment platform's secret store. Do not use `.env` in a production image or commit it to source control.

## Network and API gateway

Expose the API only through a TLS-terminating gateway. Enforce distributed per-client rate limits and identity-based authentication at the gateway. The in-process API key and rate limiter are defense-in-depth for a single instance, not a substitute for Entra ID/API Management in a multi-instance deployment.
