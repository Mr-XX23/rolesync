# Data Pipeline Service

## Identity and workspaces

- **Who:** the gateway verifies the `access_token` cookie and injects `X-User-Id`; routes take the caller from that header only (`module_1_document_processing/identity.py`).
- **Which workspace:** the knowledge vault and the catalog are shared per workspace, named by `X-Tenant-Id` (a workspace UUID). Nothing upstream verifies that header, so both check that the caller is an active member by asking workspace-service (`GET /api/v1/workspaces`, cached 60 s, re-checked live before a refusal; refused if it can't be verified). See `module_1_document_processing/workspace_access.py`. Settings: `WORKSPACE_SERVICE_URL` (default `http://workspace-service:8083`), `WORKSPACE_MEMBERSHIP_CACHE_SECONDS`.
- **Knowledge vault permissions:** every member reads and searches; VIEWERs can't change anything; the uploader (recorded as `user_id`) or an OWNER/ADMIN deletes. `GET /knowledge-vault/documents?mine=true` lists only the caller's uploads.

## Catalog search

`POST /api/v1/catalog/ai/semantic-search` ranks with BM25 over weighted product fields (name and keywords count most), with light stemming and rare words weighing more than common ones (`catalog/search_ranking.py`). With `"expand": true` (the default) an OpenRouter model first suggests synonyms (`CATALOG_QUERY_EXPANSION_MODELS`, `CATALOG_QUERY_EXPANSION_TIMEOUT_SECONDS`); callers that write precise queries can pass `"expand": false`.

## Moving data into a workspace

Data saved before workspaces were wired through the app sits under a placeholder (catalog: `00000000-0000-0000-0000-000000000001`, vault: `tenant_default`). To move it into a real workspace (dry run unless `--apply`):

```bash
docker exec data-pipeline python scripts/move_to_workspace.py --workspace <workspace uuid> --catalog-from 00000000-0000-0000-0000-000000000001 --vault-user <auth user id>
```
