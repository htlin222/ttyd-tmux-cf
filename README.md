# ttyd-tmux-cf

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/htlin222/ttyd-tmux-cf/actions/workflows/lint.yml/badge.svg)](https://github.com/htlin222/ttyd-tmux-cf/actions/workflows/lint.yml)
[![Platform: macOS](https://img.shields.io/badge/Platform-macOS-000000?logo=apple&logoColor=white)](https://www.apple.com/macos/)
[![Cloudflare Zero Trust](https://img.shields.io/badge/Cloudflare-Zero%20Trust-F38020?logo=cloudflare&logoColor=white)](https://www.cloudflare.com/zero-trust/)
[![Cloudflare R2](https://img.shields.io/badge/Cloudflare-R2-F38020?logo=cloudflare&logoColor=white)](https://developers.cloudflare.com/r2/)
[![ttyd](https://img.shields.io/badge/ttyd-1.7%2B-181717.svg?logo=gnometerminal&logoColor=white)](https://github.com/tsl0922/ttyd)
[![tmux](https://img.shields.io/badge/tmux-1BB91F.svg?logo=tmux&logoColor=white)](https://github.com/tmux/tmux)
[![Python](https://img.shields.io/badge/Python-%3E%3D3.10-3776AB.svg?logo=python&logoColor=white)](https://www.python.org)
[![Shell: bash](https://img.shields.io/badge/Shell-bash-4EAA25?logo=gnubash&logoColor=white)](https://www.gnu.org/software/bash/)
[![Claude Code Ready](https://img.shields.io/badge/Claude%20Code-Ready-D97757?logo=anthropic&logoColor=white)](CLAUDE.md)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/htlin222/ttyd-tmux-cf/pulls)
[![GitHub stars](https://img.shields.io/github/stars/htlin222/ttyd-tmux-cf?style=social)](https://github.com/htlin222/ttyd-tmux-cf/stargazers)
[![GitHub last commit](https://img.shields.io/github/last-commit/htlin222/ttyd-tmux-cf)](https://github.com/htlin222/ttyd-tmux-cf/commits/main)
[![Repo size](https://img.shields.io/github/repo-size/htlin222/ttyd-tmux-cf)](https://github.com/htlin222/ttyd-tmux-cf)
[![Issues](https://img.shields.io/github/issues/htlin222/ttyd-tmux-cf)](https://github.com/htlin222/ttyd-tmux-cf/issues)

Deploy a **persistent web terminal** (ttyd + tmux) on a Mac, gated by **Cloudflare Zero Trust** so you can log in from any browser with email OTP. Nerd Font glyphs served from **Cloudflare R2** for snappy loads on every device.

```
browser ── HTTPS ──> term.example.com (Cloudflare edge)
                      │  Cloudflare Access challenge
                      │  (email OTP to your address)
                      ▼
                cloudflared tunnel (existing, on your Mac)
                      │
                      ▼
                http://127.0.0.1:7681  (ttyd, loopback only)
                      │
                      ▼
                tmux new-session -A -s web   (persistent session)

Nerd Font glyphs load in parallel from R2:
  fonts.example.com/jbmono-nerd-{regular,bold}.woff2   (CDN-cached, immutable)
```

## Why

- Open any browser, OTP login, drop into a tmux session that survives reboots and reconnects.
- No SSH key juggling on the client. Cloudflare handles auth at the edge.
- Works on phones, tablets, borrowed laptops.

## Prereqs

- macOS with Homebrew. (Linux works too — swap LaunchAgent for systemd; see "Linux" section in `CLAUDE.md`.)
- A Cloudflare account with **a zone you own** (e.g. `example.com` on Cloudflare nameservers).
- An existing **cloudflared tunnel** running on this Mac. (Don't have one? See [Cloudflare Tunnel quick start](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/get-started/) — takes 5 min.)
- A **Cloudflare API token** with these scopes (least privilege):
  - `Account → Access: Apps and Policies → Edit`
  - `Account → Access: Organizations, Identity Providers, and Groups → Read`
  - `Account → Workers R2 Storage → Edit`
  - `Zone → Zone → Read` (any zone — used to look up the zone ID)
- `wrangler` logged in (`wrangler login`) — needed for R2 uploads.
- A copy of the **JetBrainsMono Nerd Font** TTFs (Regular + Bold) on disk, or willingness to download them. Get them from [nerd-fonts releases](https://github.com/ryanoasis/nerd-fonts/releases) (`JetBrainsMono.zip`). Any Nerd Font works — adjust `.env`.

Costs: tunnel free, Access free up to 50 users, R2 free under 10 GB / 1 M ops/month. Fonts are ~2 MB total — effectively zero.

## Quick start (with Claude Code)

```sh
git clone <this-repo> ~/ttyd-tmux-cf
cd ~/ttyd-tmux-cf
cp .env.example .env
$EDITOR .env   # fill in your hostname, email, token, etc.
```

Then in this directory, ask Claude Code:

> read the CLAUDE.md and go

Claude will preflight your tools, discover your tunnel/zone/account, create the Cloudflare Access app + policy, wire up the cloudflared ingress + DNS, provision the R2 bucket + custom domain + CORS, build a custom `index.html`, install the ttyd LaunchAgent, and verify end-to-end. It's idempotent — safe to re-run.

When it's done, open `https://<your-hostname>` in any browser, do the email OTP, and you're in tmux.

## Manual run (no Claude)

`CLAUDE.md` is also a readable runbook. Open it; each phase has copy-pasteable shell. Same result, just slower.

## File layout

```
ttyd-tmux-cf/
├── README.md                  # this file
├── CLAUDE.md                  # runbook (Claude reads this and executes)
├── .env.example               # template — copy to .env and fill in
├── .gitignore
├── examples/
│   ├── com.USER.ttyd.plist.template     # LaunchAgent template
│   ├── cloudflared-ingress-snippet.yml  # ingress fragment to add
│   └── cors.json                        # R2 CORS policy (ready to use)
└── scripts/
    └── build-index.py         # harvest ttyd's index.html and inject @font-face
```

## Rollback

`CLAUDE.md` has a `Rollback` phase at the bottom. Or by hand:

```sh
launchctl bootout "gui/$(id -u)/com.${USER}.ttyd"
# remove the term.* ingress block from ~/.cloudflared/config.yml
launchctl kickstart -k "gui/$(id -u)/com.cloudflare.cloudflared.<tunnel-label>"
# In Cloudflare dashboard: delete the Access app, delete the R2 bucket/domain.
```

## Security notes

- ttyd binds to `127.0.0.1` only — never directly reachable, even on LAN.
- Cloudflare Access enforces identity before the tunnel forwards. Defense in depth: even without Access, the tunnel hostname won't resolve directly to anything but the Cloudflare edge.
- Don't commit `.env`. `.gitignore` already excludes it.
- Revoke the API token (`https://dash.cloudflare.com/profile/api-tokens`) once setup is done; it's only needed during deploy.

## Citation

If you use this project, please cite it:

**BibTeX:**

```bibtex
@software{lin2026ttydtmuxcf,
  author  = {Lin, Hsieh-Ting},
  title   = {ttyd-tmux-cf: Persistent web terminal gated by Cloudflare Zero Trust},
  year    = {2026},
  url     = {https://github.com/htlin222/ttyd-tmux-cf},
  version = {0.1.0}
}
```

<details>
<summary>AMA format</summary>

Lin HT. ttyd-tmux-cf: Persistent web terminal gated by Cloudflare Zero Trust. Published online 2026. https://github.com/htlin222/ttyd-tmux-cf

</details>

<details>
<summary>APA format</summary>

Lin, H.-T. (2026). *ttyd-tmux-cf: Persistent web terminal gated by Cloudflare Zero Trust* (Version 0.1.0) [Computer software]. https://github.com/htlin222/ttyd-tmux-cf

</details>

## License

This project is licensed under the [MIT License](LICENSE).
