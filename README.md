# Hermes SEO Growth Monitor

**A read-only Hermes agent skill for multi-site SEO evidence collection and offline reporting.**

[Read the case study on TA551](https://ta551.info/blog/hermes-seo-automation-multi-site-audit/)

> [!IMPORTANT]
> This repository is a **Hermes skill + Python offline helper**, not an MCP server or a general-purpose SEO API client. Live data collection requires **your own authorized and correctly configured** `seo_traffic` MCP tools exposed to Hermes. Without these tools, you can test the offline renderer, but you cannot run a live SEO audit.

## What it does

- Plans 7-day and 28-day Google Search Console windows with separate previous periods.
- Accepts saved MCP responses as evidence; checks exact tool names, arguments, scope and dates before reporting.
- Generates per-site Markdown SEO reports and a consolidated summary from offline evidence.
- Treats missing data as **unknown**, not zero; distinguishes impressions, clicks, sessions and unique users.
- Supports sampled URL Inspection, sitemap status, opportunities and an **unpublished** 14-day editorial proposal.
- Processes site reports locally with Python's standard library; the Python helper makes **no API, browser, or LLM calls**.

## Requirements

- [Hermes](https://github.com/NousResearch/hermes-agent) with a compatible skill loader and an authorized `seo_traffic` MCP tool package. Tool names and schemas can vary: verify against your installation.
- Python 3.10+ (Windows is the supported local reporting platform; on Linux/macOS pass `--output`).
- Permission to inspect the relevant GSC/GA4 properties. No credentials are included or needed by the offline script.
- No Python packages need to be installed for the offline helper.

## Install and configure

1. Copy the directory containing `SKILL.md` into the skills location **for your Hermes installation**. Use Hermes' skill listing/view commands to confirm it is loaded; the path is installation-specific.
2. Verify the installed Hermes session exposes `mcp__seo_traffic__sites_list` and the other registered names in [references/workflow.md](references/workflow.md). This code **does not install** or configure the MCP server.
3. Optionally copy `config.example.json` to `config.json` and edit the `sites` mapping for domains you own. `ga4_property` is optional; if absent/null, GA4 requests are not planned. Do not put API keys or credentials in this JSON file. `config.json` is gitignored.
4. From the folder containing `SKILL.md`, generate an offline request plan:

```powershell
python scripts/monitor.py init --config config.json --site ta551.info --end 2026-10-12
```

Or try the **offline synthetic demonstration** (no Hermes/MCP connection required):

```powershell
python scripts/monitor.py init --synthetic --output .\Hermes-SEO --site ta551.info --end 2026-10-12
```

The command prints a unique run directory. Read its `requests-<domain>.json` file, collect matching **real tool responses using Hermes itself** as described in [the workflow](references/workflow.md), and record them with:

```powershell
python scripts/monitor.py capture --run "<run-directory>" --site ta551.info --label gsc-current28 --response "<saved-response.json>"
python scripts/monitor.py render --run "<run-directory>"
```

The `capture` example is only **one** evidence record. A complete live report needs the other planned records. An offline report with missing records is **partial**, not a successful live audit. Avoid committing local captures or data dumps.

### Changing domains

In `config.json`, replace the example `sites` keys with your own lowercase DNS domains:

```json
{
  "sites": {
    "example.com": {
      "gsc_property": "sc-domain:example.com",
      "ga4_property": null
    }
  }
}
```

Then run `init --config config.json --site example.com`. GA4 property IDs, when configured, are **not** authentication secrets but are intentionally excluded from the public examples. Never commit your site-specific private configuration.

## Architecture

```text
SKILL.md                 Hermes agent instructions (read-only boundary)
references/workflow.md   Native MCP tool mappings and evidence schema
scripts/monitor.py       Offline plan/capture/render, no network access
tests/                   Synthetic tests for dates, config, evidence, reports
config.example.json      Public example domains, no credentials
```

The assistant gathers data through Hermes **native MCP tools**, then hands saved JSON payloads to the Python helper. The helper validates and renders reports. There is **no background job**, automatic indexing submission, production deployment, or website modification.

## Limitations and safety

- Google sitemap counts are not a whole-site indexing count. URL Inspection is a sampled check, not site coverage.
- Query and landing-page examples are limited to 25 rows and may omit anonymized/private searches.
- GA4 summaries are limited to the *available MCP breakdowns*; do not reconstruct unique users by summing breakdown rows. If no GA4 property is configured, no GA4 request is made.
- Bing traffic/date support is limited in the referenced adapter. Only invoke Bing when access is explicitly approved and verified; otherwise mark it unavailable.
- This project does **not** provide keys, account access, a bundled MCP server, or a guarantee of indexing or traffic growth.
- Review responses before saving them as evidence. Do not store access tokens, cookies, raw auth headers or other credentials in reports.

## Resuming an interrupted audit (v1.1.0)

Hermes can call MCP tools but local models sometimes skip steps, repeat old
summaries, or cannot batch tool calls. The monitor now exposes deterministic,
read-only progress commands; they **do not bypass native MCP authorization**
or run requests automatically.

```powershell
$skill = "$env:LOCALAPPDATA\hermes\skills\seo-growth-monitor\scripts\monitor.py"
$run = "$env:USERPROFILE\Documents\Hermes-SEO\20261019-185223-e9def6"
py -3.10 "$skill" status --run "$run"
py -3.10 "$skill" next --run "$run"
```

The `next` output supplies one missing site/label, exact MCP callable and
arguments. Invoke that tool in Hermes' **native tool interface**, save its
actual raw JSON (with no invented values), and use:

```powershell
py -3.10 "$skill" capture --run "$run" --site ta551.info --label gsc-previous7 --response "$run\raw-response.json"
py -3.10 "$skill" status --run "$run"
```

Repeat `next` / native tool call / `capture` / `status` for each approved
request. The site and label in the example are illustrative; use the next
planned record instead. No automatic bulk calls or background process are
introduced. Invalid saved evidence is flagged and blocks automatic progress,
not overwritten. An unavailable provider can be explicitly skipped with
`next --skip-tool analytics_advanced`, leaving those records missing. A
partial report remains partial; run `render` after collecting available data.

## Tests

```bash
python -m unittest discover -s tests -v
python -m py_compile scripts/monitor.py
```

Tests use synthetic fixtures only; live MCP access is **not** tested here.

## Real-world write-up

[How I Used Hermes to Automate SEO Audits Across Three Websites — TA551](https://ta551.info/blog/hermes-seo-automation-multi-site-audit/)

## License

MIT License, see [LICENSE](LICENSE). This independent community skill is **not an official Hermes or SEO MCP integration**.
