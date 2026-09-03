# Collector → API JSON contract (v1)

Collectors `POST /api/ingest` with header `Authorization: Bearer <token>`.
The token is scoped to exactly one client + site; the server uses the **token's**
scope as authority. `client`/`site` in the body are informational and, if present,
must match the token or the request is rejected (409).

```jsonc
{
  "collectorVersion": "1.0.0",
  "client": "acme",                  // optional, must match token scope if sent
  "site": "milan-dc1",               // optional, must match token scope if sent
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
      "thumbprint": "AB12...",
      "daysToExpiry": 89
    }
  ],

  "licenses": [
    {
      "product": "XDT_PLT_UD",
      "edition": "Platinum",
      "model": "UserDevice",
      "count": 500,
      "subscriptionAdvantageDate": "2026-08-31",
      "expires": null                // null = permanent; ISO date = expiring
    }
  ]
}
```

### Rules
- All timestamps ISO-8601 UTC.
- On each successful ingest the server: stores the raw payload as a `snapshot`,
  **replaces** the site's derived `components` / `certificates` / `licenses` with
  this payload (latest-wins), updates the collector's `last_seen`, and re-runs
  advisory matching to refresh `findings`.
- Component `type` is an open enum; unknown types are stored but not matched.
