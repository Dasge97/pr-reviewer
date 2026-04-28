# pr-revisor

Local-first Bitbucket Cloud PR reviewer service for a shared PC.

## What it does

- Receives Bitbucket pull request webhooks through a public tunnel such as `cloudflared`
- Validates signed webhook requests for registered repositories
- Deduplicates repeated deliveries per PR revision in SQLite
- Prepares isolated bot mirrors and per-PR workspaces without touching human `main` clones
- Runs `opencode run` with a deterministic JSON-only output contract
- Creates a new Bitbucket PR comment for each accepted PR update/review run

## Layout

- `config/repos.yaml` — tracked repositories and secret env references
- `data/reviewer.db` — SQLite state
- `var/log/` — host logs
- `<bot_workspace_root>/repos/<slug>.git` — bare mirror
- `<bot_workspace_root>/workspaces/<slug>/pr-<id>` — persistent PR workspace

## Local setup

1. Create a Python 3.12 virtualenv.
2. Install dependencies:
   - `pip install -e .[dev]`
3. Copy values from `config/service.env.example` into your shell or service manager.
4. Update `config/repos.yaml` or start from `config/repos.sample.local.yaml`.
5. Ensure `git`, `opencode`, and `cloudflared` are available on PATH.

## Run locally

```powershell
uvicorn service.app:app --host 127.0.0.1 --port 8001
```

Health check:

```powershell
curl http://127.0.0.1:8001/healthz
```

## cloudflared ingress

Use the cheapest stable ingress path for v1:

```powershell
cloudflared tunnel --url http://127.0.0.1:8001
```

Point the Bitbucket webhook at:

`https://<your-tunnel-host>/webhooks/bitbucket`

## Webhook validation

This service expects:

- `X-Event-Key` with `pullrequest:created`, `pullrequest:updated`, or `pullrequest:reopened`
- `X-Hub-Signature` with `sha256=<hex hmac>`
- a repository entry in `config/repos.yaml`

## opencode output contract

`opencode run` must print JSON only:

```json
{
  "status": "changes_requested",
  "summary": "Two correctness issues found.",
  "review_body": "Detailed markdown body to post to Bitbucket.",
  "findings": ["Null case is not handled", "Missing regression test"]
}
```

The service enforces concise output limits before posting to Bitbucket:

- `summary`: max 280 chars
- `review_body`: max 1200 chars
- `findings`: max 5 items
- each finding: max 160 chars

## Requirements-first review

Before reviewing a PR, the service loads a requirements markdown file from the PR workspace and injects it into the prompt with highest priority.

- Default file: `requerimientos.md`
- Fallbacks if missing: `requirements.md`, then generic review mode
- Override filename in `config/repos.yaml` or `.pr-reviewer.yml` with `requirements_file`

## Replay a webhook locally

1. Start the service.
2. Use payloads in `tests/fixtures/`.
3. Compute the HMAC with the repo secret and send the request to `/webhooks/bitbucket`.

## Tests

```powershell
pytest
```
