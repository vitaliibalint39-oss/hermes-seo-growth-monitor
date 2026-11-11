#!/usr/bin/env python3
"""Read-only public HTTPS HEAD checks for a fixed allowlist of owned sites.

No external dependencies, no redirects, no secrets, no file writes.
Not a host health check, vulnerability scanner, or SSL expiry checker.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

SITES = ("ta551.info", "siteprobelab.com", "vitaliibalint.com")
SECURITY_HEADERS = (
    "strict-transport-security",
    "content-security-policy",
    "x-content-type-options",
    "referrer-policy",
)

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def check(site: str, opener=None, timer=None) -> dict:
    """Send exactly one HEAD request; never follow a redirect."""
    if site not in SITES:
        raise ValueError("Site is not in the explicit allowlist")
    opener = opener or urllib.request.build_opener(NoRedirect)
    timer = timer or time.monotonic
    url = "https://" + site + "/"
    result = {
        "site": site,
        "url": url,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "method": "HEAD",
        "http_status": None,
        "state": "UNAVAILABLE",
        "latency_ms": None,
        "security_headers": {},
        "error": None,
        "note": "Public HTTPS only; not evidence of host/container health.",
    }
    request = urllib.request.Request(
        url, method="HEAD", headers={"User-Agent": "Hermes-Site-Agent-Team/0.1"}
    )
    start = timer()
    try:
        with opener.open(request, timeout=8) as response:
            status, headers = response.getcode(), response.headers
    except urllib.error.HTTPError as exc:
        # Redirects and 4xx/5xx still provide useful observed status/headers.
        status, headers = exc.code, exc.headers
        exc.close()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        result["latency_ms"] = round((timer() - start) * 1000)
        result["error"] = type(exc).__name__ + ": " + str(exc)
        return result

    result["http_status"] = status
    result["latency_ms"] = round((timer() - start) * 1000)
    result["state"] = "OK" if 200 <= status < 400 else "WARNING"
    result["security_headers"] = {
        header: headers.get(header) for header in SECURITY_HEADERS
    }
    return result

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", choices=SITES, help="One allowlisted site; default: all")
    args = parser.parse_args()
    sites = (args.site,) if args.site else SITES
    report = {
        "tool": "Hermes Site Agent Team public HTTPS check",
        "mode": "read-only",
        "results": [check(site) for site in sites],
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
