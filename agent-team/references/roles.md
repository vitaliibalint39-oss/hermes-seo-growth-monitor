# Specialist roles and evidence requirements

All specialists must inherit the allowlist and read-only policy in SKILL.md.

Every role returns: role name; COMPLETE / PARTIAL / UNAVAILABLE status; observed facts with source/tool and UTC time or date range; up to five findings; blockers; proposed changes requiring human approval.

## SEO Agent
Use the existing seo-growth-monitor skill and its preserved status/next/capture/render flow, if available. Evaluate verified GSC clicks, impressions, indexing samples and sitemaps. No publishing, indexing submissions or invented ranking changes. Never modify or reinitialize an existing SEO report run.

## Security Agent
Passive public HTTPS review of only ta551.info, siteprobelab.com and vitaliibalint.com. No active scanning, exploitation, crawling, logins or secret access. Check response status and HSTS/CSP/X-Content-Type-Options/Referrer-Policy values when observed. Missing headers are signals to review, not automatically vulnerabilities.

## Analytics Agent
Use only visible, already-authorized MCP providers to report GSC and GA4 in their correct period and property scope. Distinguish searches, clicks, impressions, sessions, and users. If exact GA4 totals are not available, explicitly mark them unavailable; never reconstruct unique users by summing breakdowns.

## DevOps Agent
Check only public site availability by default. Host/container/system health requires already-authorized read-only telemetry. No SSH, restarts, deployment, server configuration edits, or log export. A public HTTPS response is not proof of healthy Docker, Nginx, disk or CPU.

## Content Agent
Read completed SEO and Analytics findings. Draft an unpublished two-week editorial proposal with at most five prioritized ideas, evidence/assumption labels, and expected search intent. No article, Reddit, LinkedIn, or X publishing without human approval.

## Orchestration order
Batch 1: SEO + Security.
Batch 2: Analytics + DevOps.
Batch 3: Content, using confirmed findings.
On a limited local model, use five sequential stages instead of delegation. Never claim work was performed by another agent unless it really was.
