# Single-run report contract

Title: Hermes Site Agent Team review
Report date/time: timestamp with timezone.
Targets: ta551.info, siteprobelab.com, vitaliibalint.com.
Mode: read-only.
Execution: delegated or sequential (say which actually happened).
Overall status: COMPLETE / PARTIAL / UNAVAILABLE.

## Site status
For each authorized site state:
- HTTPS response code and observation time, or unavailable.
- SEO GSC status and evidence period, or unavailable.
- GA4 status and evidence period, or unavailable.
- Public security header values and limitations.
- DevOps: public-only check or verified host telemetry (label correctly).
- Unpublished content suggestions based on observed evidence or clearly labeled hypotheses.

## Role evidence
For each of five roles give:
- Status: COMPLETE / PARTIAL / UNAVAILABLE
- Evidence source: URL, native MCP tool, or existing saved checkpoint
- Date or date range
- Top findings (maximum five)
- Explicit blockers / unknowns

## Top 3 prioritized proposals
Each: why it matters, verified evidence, estimated effort (rough), and human approval needed.

## Safety
Never report missing as zero. Never claim live MCP success based on synthetic data.
No publishing, deployments or configuration edits occurred. If a human explicitly
requested one later, that would need separate authorization.
