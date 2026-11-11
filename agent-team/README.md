# Hermes Site Agent Team (read-only beta)

This extension adds five bounded specialist roles (SEO, Security, Analytics,
Content, DevOps) to the user's existing Hermes SEO Growth Monitor setup.

- Hermes orchestrates using delegate_task when available, or sequentially.
- Existing seo-growth-monitor and its saved run/checkpoint stay untouched.
- No new MCP server, keys, permissions, cron job or background daemon is installed.
- GSC/GA4 need already configured and authorized native Hermes MCP tools.
- Public health checker requires Python 3.10+ and no third-party packages.

## Install in Windows PowerShell (after reviewing this branch)

Run in a fresh working folder:

    git clone --branch feature/hermes-agent-team-readonly https://github.com/vitaliibalint39-oss/hermes-seo-growth-monitor.git
    $source = Join-Path (Get-Location) 'hermes-seo-growth-monitor\agent-team'
    $destination = Join-Path $env:LOCALAPPDATA 'hermes\skills\site-agent-team'
    if (Test-Path $destination) { throw 'Skill folder already exists. Back it up before any replacement.' }
    New-Item -ItemType Directory -Path $destination | Out-Null
    Copy-Item (Join-Path $source 'SKILL.md') -Destination $destination
    Copy-Item (Join-Path $source 'references') -Destination $destination -Recurse
    Copy-Item (Join-Path $source 'scripts') -Destination $destination -Recurse

Use your existing local Hermes installation; never reset its model, MCP or
seo-growth-monitor config merely to install this skill.

Check visibility in a fresh session (CLI support depends on Hermes version):

    hermes skills list

Ask Hermes:

    Use site-agent-team to review ta551.info, siteprobelab.com and vitaliibalint.com.
    Run read-only checks only. Delegate at most two specialists at a time if supported.
    Use authorized MCP tools when visible; preserve SEO checkpoints.
    Return evidence, provider gaps and three prioritized recommendations.
    Do not publish, deploy, or change remote configuration.

## Offline tests (no HTTP request)

    py -3.10 -m unittest discover -s .\hermes-seo-growth-monitor\agent-team\tests -v

## Public-only check (three HEAD requests)

    py -3.10 .\hermes-seo-growth-monitor\agent-team\scripts\public_health.py

JSON prints to standard output; script does not write files or follow redirects.
It does not prove host, Docker or Nginx health. Missing headers are not by
themselves proven vulnerabilities.

## Optional recurring run (not enabled by this repo)

After verifying a successful manual run and that your installed Hermes
version supports cron, you can opt in to a weekday 9 AM job:

    hermes cron create "0 9 * * 1-5" "Run site-agent-team read-only for the three authorized sites. Summarize verified data; do not publish or deploy." --skill site-agent-team --name "Site Agent Team Daily"
    hermes cron list
    hermes cron status

Verify the gateway service and time zone. On a local small model, prefer a
weekly schedule or manual invocations if inference is slow. No job is
created automatically.

## Known limitations

The agent team cannot make unavailable private analytics suddenly appear.
Some Hermes versions lack delegate_task; the skill falls back to sequential
stages and must say so. Scheduling is dependent on the user's running
Hermes gateway. A real end-to-end test must run on the user's computer
with its existing Hermes / MCP setup.
