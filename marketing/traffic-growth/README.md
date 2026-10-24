# Hermes Traffic Growth MVP v1

Isolated, manually operated marketing helper, Python 3.10+ standard library only.
The existing SEO monitor is unchanged. No deployment, paid API, publishing,
messaging, model download, or background scheduling is implemented.

Run commands from the repository root. On Windows use `py -3`; on other systems
replace it with `python3`. Global `--data PATH` goes **before** the command.
Default output is `marketing/traffic-growth/data/` (gitignored). Use separate
data directories for separate planning periods. Run one writer at a time.
Writes use unique same-directory temporary files and atomic replacement. The
workflow supports a single writer per data directory; concurrent commands are
not serialized and may overwrite each other's updates. Existing symlinked data
directories and destination files are refused where the platform exposes them.
Windows reparse points and filesystem races cannot be ruled out portably, so use
a private, ordinary directory for `--data`. A custom path inside the repository
may be tracked unless covered by `.gitignore`; prefer a location outside the
checkout or verify it with `git status` and `git check-ignore`.

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
The API's returned model ID must exactly match `--model`; there are no implicit
aliases. A response model ID is provenance supplied by that API and does not
prove which hardware or service performed inference.
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

### Provider compatibility and the verified local Qwen

Run the main CLI directly; no `data/` adapter is needed:

```powershell
py -3 marketing/traffic-growth/traffic_growth.py draft --provider lmstudio --model qwen3.5-4b-instruct --platform linkedin --response-format json_schema --thinking off --max-tokens 4096 --timeout 120
```

This exact model ID was returned by the local LM Studio server. Model IDs on
other installations must be obtained from their own server, not guessed.

| Option | LM Studio `/v1/chat/completions` | Ollama `/api/chat` |
| --- | --- | --- |
| `--response-format json_schema` | Named strict JSON Schema (default) | Schema object in `format` |
| `--response-format json` | `json_object`, only if supported | `format: json` (default) |
| `--response-format text` | `response_format.type: text` | Omit `format` |
| `--thinking default` | Omit thinking parameter | Omit thinking parameter |
| `--thinking off` | `reasoning_effort: none` | `think: false` |
| `--thinking on` | `reasoning_effort: on`, only if supported | `think: true`, only if supported |
| `--max-tokens N` | `max_tokens` | `options.num_predict` |

Modes are explicit provider-specific requests, not universal capability claims.
Leave thinking at `default` unless the model/API supports the selected setting.
Models requiring named effort levels rather than boolean thinking may not accept
`on`; no unsupported mode is silently substituted. This LM Studio installation
rejects `json_object`; the verified Qwen path uses `json_schema` and
`reasoning_effort: none`. The native API's `reasoning: off` is not used for chat
completions. Ollama integration is covered by offline protocol tests; a live
Ollama inference has not been verified here.

The default output budget is 4096 (allowed range 1–32768); `--timeout` sets the
socket operation timeout in seconds (default 120, range 1–600), not an absolute
wall-clock deadline. HTTP errors, connection failures and timeouts fail visibly
without saving a draft or retrying inference automatically. Raw HTTP error bodies
are not printed. Unsupported options require an explicit corrected command.

In every format, the response must still be JSON containing only `quotes`: 1–3
unique strings matching complete eligible source lines (20–900 characters).
Schema mode constrains choices to those lines. Local validation enforces the
same schema even if a server ignores it; duplicate JSON keys and nonstandard
constants are rejected. Text mode does not accept arbitrary prose or code fences.

LM Studio must return exactly one completion with `finish_reason: stop` and
nonempty content. Ollama must return `done: true` and, when present,
`done_reason: stop`; legacy responses without `done_reason` retain a null reason
in provenance. Refusals, tool calls, malformed envelopes and truncated output
are rejected. With thinking explicitly off, reported reasoning text or nonzero
reasoning tokens also reject the response. Absent telemetry cannot independently
prove that a server honored a setting.

Saved generation provenance records requested options, returned model ID, finish
reason and provider usage. Identical normalized draft text from different models
shares one draft record only when the source URL, source hash and platform also
match; every inference is retained in `model_provenance`. Separate source URLs
remain separate records. Rerunning does not reset draft status.

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
Local JSON and CSV input is limited to 2 MB per file; `inventory --html` accepts
up to 2 MiB. Both use bounded byte reads, and CSV fields are limited to 1 MB.
Oversized, malformed, or invalid UTF-8 input fails before replacing saved data.
Quoted multiline CSV fields are supported.

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
py -3 marketing/traffic-growth/traffic_growth.py calendar --entry 1 --status approved --draft-id YOUR_DRAFT_ID --reviewed
py -3 marketing/traffic-growth/traffic_growth.py calendar --entry 1 --status published --reviewed
```

Only `draft -> approved -> published` is allowed. `--reviewed` is your explicit
attestation that you manually reviewed the exact saved draft. Approval stores its
draft ID and SHA-256 of the exact body. Before an approval is used, the CLI checks
that the draft still exists and its ID, source, platform and content hash match.
The SHA-256 detects content changes relative to the approval record; it does not
authenticate who approved the text. A local user who can edit both draft and
calendar JSON can forge an approval record. Keep the data directory private and
have the operator review the exact draft manually before approval.
An edited, removed or legacy unbound pending approval is invalidated to `draft`.
If a previously `published` local record's draft changes, the historical status
remains and its approval is marked invalid. The `published` status only records a
manual action locally; no publishing API or automatic publication path exists.

## Offline CLI smoke check

With a saved UTF-8 article fixture, the following commands do not contact the
website or a model server:

```powershell
py -3 marketing/traffic-growth/traffic_growth.py --data $env:TEMP\hermes-traffic-smoke inventory --url https://ta551.info/blog/wazuh-ai-security-lab/ --html path\to\saved-article.html
py -3 marketing/traffic-growth/traffic_growth.py --data $env:TEMP\hermes-traffic-smoke calendar --start 2026-10-23
py -3 marketing/traffic-growth/traffic_growth.py --data $env:TEMP\hermes-traffic-smoke report
```

The checked-in unit test runs these same offline CLI operations with synthetic
HTML in an isolated temporary directory. Replace the fixture path with a saved
article file; the supplied URL is only its catalog identity.

## Validation

```powershell
py -3 -m unittest discover -s tests -v
py -3 -m py_compile marketing/traffic-growth/traffic_growth.py
```

The current complete suite contains 61 tests, including the SEO monitor and
Traffic Growth regression tests. It ran on Windows with Python 3.10.0. Both
provider protocols, model identity checks, errors, and offline CLI commands are
tested without network access; this validation run did not contact LM Studio or
Ollama. An earlier project phase recorded a successful real LM Studio inference
with `qwen3.5-4b-instruct`; that historical result was not repeated here. Runtime
captures and GA4 data stay outside version control by default.

Known limits: this run did not test Linux or other Python versions. Symlink checks
cannot portably detect every Windows reparse point or eliminate path races. The
workflow supports one writer per data directory; simultaneous writes are not
serialized. Exact source quotes do not establish independent factual truth, and
human review remains required before approval or any manual publication.
