# Hermes Traffic Growth MVP v1

Adds an isolated, manually operated workflow for cataloging ta551.info articles,
preparing source-grounded LinkedIn, Reddit and DEV.to drafts, recording UTM links,
importing session-scoped GA4 CSV snapshots, and planning a 14-day calendar. The
existing SEO monitor is unchanged.

Implementation status: the Phase 5A attribution, source-integrity, alias and HTML
extraction fixes (M1-M4), Phase 5B atomic-write, ignore, malformed-input and
Windows-output fixes (M5-M8), and Phase 5C model identity, duplicate detection,
content-bound approval, endpoint-port validation and CI action pinning (L1-L6)
are implemented with regression coverage. Independent Final Quality Gate review
is still pending.

Draft generation supports local Ollama and LM Studio chat APIs over loopback only.
The response model ID must exactly equal the requested ID; no aliases are assumed.
Model IDs are provider-reported provenance and do not prove that inference was
performed locally. Responses are validated against exact source lines. Draft
deduplication is independent of model ID while retaining each inference in
`model_provenance` and keeping different source URLs distinct.

Calendar approval requires `--reviewed` and `--draft-id`. It records the draft ID
and SHA-256 of the exact approved body. Edited, removed, mismatched, or legacy
unbound approvals fail closed or return to `draft`. The `published` state is a
manual local record only; there is no publishing integration or automatic path.
The hash detects content changes relative to the approval record but does not
authenticate the approver. A local user able to edit both draft and calendar JSON
can forge approval; manual operator review remains required.

Validation after integrating `origin/main`: 61/61 Python unit tests passed on
Windows with Python 3.10.0. Coverage includes prior SEO monitor checks, M1-M8 data-integrity and input-safety
regressions, model identity, content deduplication, approval binding, endpoint
ports, CP1252 output, and offline CLI operations. Local provider tests are mocked;
this validation run did not exercise live Ollama or LM Studio inference. A prior
project phase recorded a successful local Qwen inference, which was not repeated
for this change. Linux and other Python versions were unavailable for verification.

GitHub Actions remains limited to push/pull-request tests with `contents: read`.
Checkout and setup-python are pinned to reviewed release commits. No deploy,
production action, secret, paid API, publishing API, message or external write is
added. Filesystem writes stay in the selected local data directory; custom paths
inside the checkout may be tracked unless ignored. Symlink/reparse-point checks
have platform limits, and concurrent writers are unsupported.

Human review remains necessary for factual context, source quality and community
rules. This PR does not claim production readiness.
