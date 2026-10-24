# Gmail Connection via Composio

OpenPoke reaches Gmail through [Composio](https://composio.dev/). Composio runs the Google OAuth flow and stores your tokens, and the server executes Gmail actions through the Composio SDK. All Composio calls live in [server/services/gmail/client.py](../server/services/gmail/client.py).

## Configuration
Set these in `.env`, then restart the server:

- `COMPOSIO_API_KEY`: from the Composio dashboard under **Settings → API Keys**.
- `COMPOSIO_GMAIL_AUTH_CONFIG_ID`: the `ac_…` ID of a Gmail auth config, from the dashboard under **Auth Configs**. A Composio-managed OAuth2 config is the simplest choice, since it needs no Google Cloud project of your own.

`make check-env` confirms both are set.

## How connecting works
1. The web app generates a user ID (`web-<uuid>`) and stores it in localStorage as `openpoke_user_id`.
2. `POST /api/v1/gmail/connect` calls `connected_accounts.link(user_id, auth_config_id)` and returns the Google sign-in URL.
3. After you sign in, Composio stores the connected account under that user ID.
4. `POST /api/v1/gmail/status` confirms the connection and records the user ID as the server's active Gmail user. Every Gmail tool call uses this ID.

The active user ID is held in memory only. After a server restart, open **Settings** in the web app so it sends the stored ID again; until then Gmail tools report that Gmail isn't connected.

## `link()` instead of `initiate()`
Composio retired the legacy `POST /api/v3/connected_accounts` endpoint, which the SDK's `connected_accounts.initiate()` wraps, for Composio-managed OAuth auth configs (cutover 2026-05-08 for new organizations, 2026-07-03 for all others). Calling it now fails with:

```
ComposioLegacyConnectedAccountsEndpointRetiredError: 400 Creating connections on this endpoint for Composio-managed OAuth auth configs is no longer supported. Use POST /api/v3/connected_accounts/link instead.
```

OpenPoke uses `connected_accounts.link()`, which works for both Composio-managed and custom OAuth auth configs and returns the same `ConnectionRequest` shape. It needs `composio>=0.8.14`; if you see the error above, reinstall dependencies with `make install`.

See Composio's changelog entry: <https://docs.composio.dev/docs/changelog/2026/04/24>.
