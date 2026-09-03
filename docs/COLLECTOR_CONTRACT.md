# Collector → API JSON contract (v1)

Probes `POST /api/ingest` with header `Authorization: Bearer <token>`. On the first
push the token is the **enrollment token** generated in the dashboard when the
client was created; the response then carries `collectorToken`, the probe's
**permanent per-probe token**, which the probe saves and uses for every later push.
The client is bound by the enrollment token (the `client` field below is
informational); the `site` is auto-created under that client from its name.

```jsonc
{
  "collectorVersion": "1.0.0",
  "client": "ACME Corp",             // display name; slug auto-derived (acme-corp)
  "site": "Milan DC1",               // display name; slug auto-derived (milan-dc1)
  "probe": "DDC01",                  // probe identity (e.g. hostname); optional
  "collectedAt": "2026-09-03T10:00:00Z",

  "components": [
    {
      "type": "delivery-controller", // controller|vda|storefront|netscaler|license-server|hypervisor
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
  ]
}
```

### Rules
- All timestamps ISO-8601 UTC (stored as naive UTC server-side).
- `site` is required; `client` is informational (the token binds the client).
- The enrollment token is temporary and time-boxed; the per-probe token it yields
  is scoped to that one probe's site. A leaked probe config exposes only that probe.
- On each successful ingest the server: stores the raw payload as a `snapshot`,
  **replaces** the site's derived `components` / `certificates` / `licenses` with
  this payload (latest-wins), updates the collector's `last_seen`, and re-runs
  advisory matching to refresh `findings`.
- Component `type` is an open enum; unknown types are stored but not matched.
