# Contributing

Thanks for considering a contribution! This repo is a runbook + small scripts, so most contributions are doc tweaks, idempotency fixes, or platform ports.

## Ground rules

- The single source of truth for what to deploy is `CLAUDE.md`. Keep it readable as a human runbook **and** safe for Claude Code to execute end-to-end.
- Idempotency is sacred: every step must converge when re-run. If you add a step, add a "skip if already present" check next to it.
- Don't bake in secrets, hostnames, emails, or account IDs anywhere except `.env.example` (which uses placeholders).
- Prefer **shell + curl + standard tools** over new dependencies. Adding a runtime is a big deal; justify it in the PR.

## Local setup

```sh
git clone https://github.com/htlin222/ttyd-tmux-cf.git
cd ttyd-tmux-cf
cp .env.example .env  # do not commit
$EDITOR .env
```

You need a real Cloudflare account + zone + tunnel to test end-to-end (the runbook is integration-heavy). Use a throwaway hostname like `term-dev.<your-zone>` so you don't clobber a real deployment.

## Testing a change

1. Pick a hostname you don't mind tearing down.
2. Edit `CLAUDE.md` or `scripts/build-index.py`.
3. Re-run the runbook from the relevant phase (Claude Code: `read CLAUDE.md and go`).
4. Verify with the commands in **Phase 7 — verify**.
5. Tear down with the **Rollback** phase.

A change is considered safe when:

- Running the runbook from scratch on a clean Mac works.
- Running the runbook a second time on top of itself is a no-op (idempotency).
- The `lint` GitHub Actions workflow stays green.

## Code style

- **Shell**: assume `bash`. Start non-trivial scripts with `set -euo pipefail`. Quote variables. Prefer `python3` for anything that needs parsing or JSON.
- **Python**: 3.10+. Standard library only unless absolutely needed. Pass `ruff check scripts/` locally.
- **YAML/JSON**: indent 2 spaces. Keep keys lower-snake-case for YAML, lowerCamel for R2 CORS schema (Cloudflare's choice).

## Commit & PR

- Branch from `main`. Name the branch by intent (`fix/idempotent-cors`, `feat/linux-systemd`).
- One logical change per PR. Update `README.md` and `CLAUDE.md` together if the user-facing flow changes.
- Reference the phase you touched in the PR description ("Phase 5: switch wrangler r2 object put to streaming upload").
- Squash-merge by default.

## Security

- **Never** paste your `.env`, API tokens, Access policies, or tunnel JSON into issues, PRs, or screenshots.
- If you find a security issue (e.g. a way the runbook leaves the hostname unprotected briefly), email rather than file a public issue.
- API tokens used during development should be short-lived; revoke after testing.

## Adding a platform

Linux (systemd) notes already live at the bottom of `CLAUDE.md`. To extend further (e.g. NixOS module, Docker compose), open a discussion first so we can agree on whether to keep it in this repo or split it out.

## Releases

Maintainers tag releases as `vMAJOR.MINOR.PATCH` (semver). A new release on GitHub triggers Zenodo archival and a fresh DOI — only tag when the runbook actually changed in a user-visible way.
