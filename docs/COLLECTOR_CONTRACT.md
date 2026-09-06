# Agent → API ingest contract (v1)

Agents `POST /api/ingest` with `Authorization: Bearer <agent token>` — the permanent
per-agent token issued by `POST /api/agent/enroll` (see `AGENT.md` §6.2). Any other
token is rejected with 401; there is no enrollment-on-push.

```jsonc
{
  "collectorVersion": "0.4.0",       // agent version
  "client": "ACME Corp",             // informational; the token binds client + site
  "site": "Milan DC1",               // display name (informational for enrolled agents)
  "probe": "MGMT01",                 // agent identity (hostname)
  "collectedAt": "2026-09-06T10:00:00Z",

  "components": [
    {
      "type": "controller",          // controller|vda|storefront|netscaler|license-server|hypervisor
      "hostname": "DDC01",
      "product": "Citrix Virtual Apps and Desktops",
      "version": "2402",
      "build": "2402.0.1000",
      "osVersion": "Microsoft Windows Server 2022 Standard 10.0.20348",
      "extra": {}                    // free-form, per-type details
    }
  ],

  "certificates": [
    {
      "source": "netscaler",         // storefront|netscaler
      "hostname": "ns01",
      "subject": "gateway.acme.com",
      "issuer": "DigiCert TLS RSA SHA256 2020 CA1",
      "notAfter": "2026-12-01T00:00:00Z",
      "thumbprint": "AB12..."
    }
  ],

  "licenses": [
    {
      "product": "XDT_PLT_UD",
      "edition": "Platinum",
      "model": "UserDevice",
      "count": 500,
      "subscriptionAdvantageDate": "2026-08-31T00:00:00Z",
      "expires": null                // null = permanent; ISO date = expiring
    }
  ],

  "diagnostics": [                   // optional: per-check outcome of this collection
    { "name": "netscaler", "version": "1.0.0", "status": "ok", "durationMs": 1480,
      "warnings": [], "error": null }
    // status: ok | warn | error | skipped
  ]
}
```

### Rules
- All timestamps ISO-8601 UTC (stored as naive UTC server-side).
- On each successful ingest the server: stores the raw payload as a `snapshot`,
  **replaces** the site's derived `components` / `certificates` / `licenses` with
  this payload (latest-wins), updates the collector's `last_seen` and `last_run`
  (from `diagnostics`), and re-runs advisory matching to refresh `findings`.
- Because ingest is latest-wins, the agent does **not** push when every check
  failed or was skipped — diagnostics then travel with the next check-in instead,
  so a broken run never wipes a site's inventory.
- Component `type` is an open enum; unknown types are stored but not matched.
- A leaked agent token exposes only that agent's site: its push rights and the
  credentials its site config references.
