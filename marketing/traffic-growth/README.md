# Hermes Traffic Growth MVP v1

Isolated, manually operated marketing helper, Python 3.10+ standard library only.
The existing SEO monitor is unchanged. No deployment, paid API, publishing,
messaging, model download, or background scheduling is implemented.

Run commands from the repository root. On Windows use `py -3`; on other systems
replace it with `python3`. Global `--data PATH` goes **before** the command.
Default output is `marketing/traffic-growth/data/` (gitignored). Use separate
data directories for separate planning periods. Run one writer at a time.

## First case: Wazuh AI security lab

```powershell
py -3 marketing/traffic-growth/traffic_growth.py inventory --url https://ta551.info/blog/wazuh-ai-security-lab/
py -3 marketing/traffic-growth/traffic_growth.py utm --source linkedin --medium social --campaign wazuh-lab --content day01
py -3 marketing/traffic-growth/traffic_growth.py calendar --start 2026-10-24
py -3 marketing/traffic-growth/traffic_growth.py report
```

Inventory fetches only explicitly supplied HTTPS ta551.info article URLs. Repeat
`--url` for more articles. It extracts `<article>` text and its `<h1>`, excludes
scripts/styles/navigation/footer, and records the retrieval time, content SHA256,
source URL and stable article ID. Query strings/fragments and www are normalized.
Repeated URLs update existing records; identical content is stored once with aliases.
It does not crawl the entire site or treat retrieval time as publication time.
Redirects are refused. A page without usable article markup fails visibly.

For offline use, add `--html saved-article.html` with exactly one `--url`.
That input is explicitly marked `local-html`, not a verified live capture.

## Local AI drafts and source checks

Start your own local server with an already installed model. The helper neither
starts servers nor installs models. Supply its exact model identifier:

```powershell
py -3 marketing/traffic-growth/traffic_growth.py draft --provider ollama --model YOUR_LOCAL_MODEL --platform linkedin
py -3 marketing/traffic-growth/traffic_growth.py draft --provider lmstudio --model YOUR_LOCAL_MODEL --platform reddit
py -3 marketing/traffic-growth/traffic_growth.py draft --provider lmstudio --model YOUR_LOCAL_MODEL --platform devto
```

`--url` defaults to the first case URL. `--endpoint http://127.0.0.1:PORT` changes
the local port (no `/v1` suffix). Only loopback HTTP origins are accepted;
proxies and redirects are disabled. Defaults: Ollama port 11434, LM Studio 1234.
The protocols follow [Ollama chat](https://docs.ollama.com/api/chat) and
[LM Studio chat completions](https://lmstudio.ai/docs/developer/openai-compat/chat-completions).
The server must be configured to perform inference locally, using a local model.

This MVP deliberately generates **extractive reading-note drafts**: the model
selects 1–3 complete source lines. Exact matching rejects fabricated text,
partial quotes, duplicate quotes, malformed JSON and incomplete responses.
Platform-specific wrappers, citations, source hash, model and validation state
are stored in `drafts/*.json`. Nothing is automatically approved or posted.

Exact matching proves source support, **not independent factual truth**. Review
the article's linked evidence, quote context, omitted caveats, length, attribution,
and each community's rules before using a draft. A source can contain false or
malicious statements. The helper does not execute article/model instructions.
Free-form AI paraphrases and independent evidence crawling are outside this MVP.
Connection errors do not produce substitute or invented AI output.

## Campaign CSV and GA4 import

UTM values use lowercase letters/digits/underscores/hyphens. Repeated generation
does not duplicate a URL in `campaigns.csv`. All incoming query parameters are
removed before the four tracking parameters are generated. Use a unique content
value for each post; the tuple source/medium/campaign/content identifies attribution.

Export a GA4 report with **session-scoped** dimensions and Sessions, then prepare
the following CSV (the example is synthetic, not measured campaign traffic):

```csv
date,sessionSource,sessionMedium,sessionCampaignName,sessionManualAdContent,sessions
2026-10-24,linkedin,social,wazuh-lab,day01,12
```

Also accepted: `Date,Session source,Session medium,Session campaign,Session manual ad content,Sessions`,
UTF-8 BOM, `#` comment lines, and dates as `20261024`. No other columns are accepted.
Remove export totals/summary rows before import. Do not combine overlapping
exports; duplicate dimension rows, invalid dates, missing/negative metrics fail.

```powershell
py -3 marketing/traffic-growth/traffic_growth.py report --ga4-csv path/to/ga4.csv
```

Each import replaces the local GA4 snapshot, preventing repeated-import inflation.
The report matches all four campaign dimensions, sums observed sessions, and lists
observed dates. Missing rows are `null` (unknown); measured zeros stay zero.
Sessions are neither clicks nor unique users. No coverage, conversion, causal
impact, period comparison or growth claims are inferred. The schema is deliberately
narrow; arbitrary GA4 exports need column selection first. No GA4 API is called.

## Calendar review

The 14 consecutive dates rotate inventory articles and platforms. With one article
this is a planning scaffold, not a recommendation to repost it every day. Review
spacing and rewrite angles manually. Re-running preserves recorded statuses.

```powershell
py -3 marketing/traffic-growth/traffic_growth.py calendar --entry 1 --status approved --reviewed
py -3 marketing/traffic-growth/traffic_growth.py calendar --entry 1 --status published --reviewed
```

Only `draft -> approved -> published` is allowed. `--reviewed` is your explicit
attestation that review or external publication occurred. `published` only records
that fact locally; it never publishes. Calendar slots and draft files are separate:
slot approval does not automatically certify a particular draft file. Verify its
source hash against the current inventory before use.

## Validation

```powershell
py -3 -m unittest discover -s tests -v
py -3 -m py_compile marketing/traffic-growth/traffic_growth.py
```

The suite includes all 9 unchanged SEO tests and 13 marketing tests. Model protocol
tests use mocks, not a running model. The demo inventory was successfully retrieved
from the live case-study URL during implementation. Live local-model inference
has not been validated in this environment. Runtime captures and GA4 data stay
outside version control by default.
