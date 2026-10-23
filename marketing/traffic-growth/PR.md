# Add isolated Hermes Traffic Growth MVP v1

Adds a manual content promotion workflow under `marketing/traffic-growth` without
changing the existing SEO monitor. The Wazuh AI security lab article is the first
demonstration source.

- Inventory: read-only article retrieval, JSON catalog, normalized URLs and content deduplication.
- Drafts: loopback Ollama/LM Studio adapters; source-matched excerpts for LinkedIn, Reddit and DEV.to.
- Tracking: idempotent UTM campaign CSV and validated session-scoped GA4 CSV snapshot import.
- Planning: 14-day calendar and explicit manual status transitions; JSON report.
- Documentation and offline unit tests. No third-party dependencies.

Validation: `py -3 -m unittest discover -s tests -v` — 22 tests pass, including all
9 existing SEO tests. Live HTTPS inventory retrieval succeeded for the demo URL.
Both model protocols are mocked in tests; actual local inference remains unverified.

Limitations: extractive drafts require human context and factual review. Calendar
entries are planning slots, not automatically linked approvals of draft files.
GA4 imports require the documented dimensions, and unavailable metrics remain unknown.

No production changes, automatic publication, messages, paid APIs or push.
