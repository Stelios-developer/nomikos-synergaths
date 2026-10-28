# Local n8n

Run `docker compose up -d` from this directory, then open
http://localhost:5678. n8n asks you to create the local owner account on the
first visit.

`agent-orchestrator.workflow.json` defines the NOMIKOS SYNERGATHS Agent Orchestrator. It
contains the complete application-triggered case flow, the mandatory evidence
gate, and visible, independent on-demand branches for Document Assistant,
Supervisor, Research, and Expert Review.

The product rebrand changes only the template's display name and introductory
note. Existing workflow IDs and webhook paths stay unchanged. Editing this file
does not update an already-imported workflow: sign in to the n8n editor and
rename the existing workflow and its introductory note in place. Do not reimport
just to change branding: the CLI import can deactivate an active workflow in
regular deployment mode. Historical exports remain unchanged.

- `POST /webhook/nexus-agent-orchestrator/case` receives a pre-indexed PDF
  from the application.
- The core chain calls `/integrations/n8n/cases/start`, then `/document-dna`,
  `/facts`, `/risks`, `/draft-action-pack`, `/audit`, and `/finalize`.
- The specialist webhooks each call one real backend adapter: `/analyze`,
  `/agents/supervisor`, `/agents/research`, or `/agents/expert-review`.

The application passes `X-N8N-API-Key` and `X-Workspace-ID` to its webhook.
n8n forwards these transient headers; the backend validates them before every
agent endpoint. No API key is saved in the workflow definition or exposed to
node-level environment expressions. The full case file remains server-side,
and every case ID is checked against its workspace.

The compose configuration disables saving execution payloads and keeps pruning
enabled because the webhook input includes a secret header and document context.
This only affects future runs; previously saved executions and backups need a
separate, operator-reviewed cleanup. The editor remains available, but execution
history will not contain node payloads for debugging. Do not enable execution
data retention for customer documents without a documented privacy review.

The audit is compulsory. If its structured verdict is missing or any claim is
not supported by the document evidence, the workflow takes the human-review
branch and no automatic action is created.

When the backend runs locally, the workflow uses
`http://host.docker.internal:8000` inside n8n. When it is deployed to Render,
replace that host with its HTTPS public URL and set the backend's
`N8N_ORCHESTRATOR_URL` to the matching n8n webhook URL.

`manual-pdf-upload-workflow.template.json` is retained as a legacy reference;
it is not the production application path. It uses `$env` expressions and is
intentionally incompatible with the hardened `N8N_BLOCK_ENV_ACCESS_IN_NODE=true`
setting; do not activate it in this instance.
