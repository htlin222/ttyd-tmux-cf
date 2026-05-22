# CLAUDE.md — runbook for `ttyd-tmux-cf`

> You are about to deploy a ttyd + tmux web terminal on this Mac, gated by Cloudflare Zero Trust, with Nerd Font glyphs served from R2. The user has cloned this repo and asked you to "read CLAUDE.md and go". Follow this file phase-by-phase. It is idempotent — re-running it must converge to the same state.

## Operating rules

1. **Never commit `.env`.** It contains a Cloudflare API token. `.gitignore` already excludes it; do not weaken it.
2. **Refuse to print the token.** Read it into a shell var, use it, never echo it. Use `${CF_API_TOKEN:0:4}…` if you must reference it.
3. **Idempotency.** Before creating anything (Access app, R2 bucket, DNS record, LaunchAgent), check if it already exists and skip / update accordingly. Don't fail loudly on "already exists" — log and continue.
4. **Confirm before destructive ops.** Anything that overwrites user config (e.g. an existing `cloudflared/config.yml` ingress with a different service) must surface the diff and ask the user first.
5. **macOS-first.** This runbook assumes macOS + LaunchAgent. For Linux, see the section at the bottom.
6. Create a TodoWrite task list per phase below.

## Phase 0 — load `.env`

If `.env` does not exist in the repo root:

```sh
cp .env.example .env
```

Then `AskUserQuestion` for each missing value (hostname, email, token, fonts hostname). Save back to `.env`. Once `.env` exists, source it for subsequent steps:

```sh
set -a; . ./.env; set +a
chmod 600 .env
```

Validate required keys are set: `CF_API_TOKEN`, `HOSTNAME`, `ALLOWED_EMAIL`, `FONTS_HOSTNAME`. If `TUNNEL_NAME` is blank, auto-detect from `cloudflared tunnel list` (pick the only running tunnel, or ask).

## Phase 1 — preflight

```sh
# Required commands
for cmd in cloudflared ttyd tmux wrangler python3 curl dig plutil launchctl; do
  command -v "$cmd" >/dev/null || { echo "MISSING: $cmd"; exit 1; }
done

# Install woff2 tools if absent
command -v woff2_compress >/dev/null || brew install woff2

# Verify wrangler is logged in and can list R2 buckets
wrangler whoami
wrangler r2 bucket list >/dev/null || { echo "wrangler r2 access missing — run 'wrangler login' and approve R2 scope"; exit 1; }

# Verify CF_API_TOKEN
curl -sf -H "Authorization: Bearer $CF_API_TOKEN" \
  https://api.cloudflare.com/client/v4/user/tokens/verify \
  | python3 -c "import json,sys; r=json.load(sys.stdin); print('token:', r['result']['status']); exit(0 if r['success'] else 1)"
```

If any check fails, fix and re-run. Don't continue with a broken environment.

## Phase 2 — discover account, zone, tunnel

```sh
# Tunnel + account
TUNNEL_NAME=${TUNNEL_NAME:-$(cloudflared tunnel list 2>/dev/null | awk 'NR>1 && NF { print $2; exit }')}
TUNNEL_ID=$(cloudflared tunnel list 2>/dev/null | awk -v n="$TUNNEL_NAME" '$2==n {print $1; exit}')
CREDS=~/.cloudflared/${TUNNEL_ID}.json
ACCOUNT_ID=$(python3 -c "import json; print(json.load(open('$CREDS'))['AccountTag'])")

# Zone for HOSTNAME (e.g. term.example.com → example.com)
ZONE_NAME=$(python3 -c "p='${HOSTNAME}'.split('.'); print('.'.join(p[-2:]))")
ZONE_ID=$(curl -sf -H "Authorization: Bearer $CF_API_TOKEN" \
  "https://api.cloudflare.com/client/v4/zones?name=$ZONE_NAME" \
  | python3 -c "import json,sys; r=json.load(sys.stdin); print(r['result'][0]['id']) if r['result'] else exit(1)")

# Same for fonts hostname (might be the same zone, might differ)
FONTS_ZONE_NAME=$(python3 -c "p='${FONTS_HOSTNAME}'.split('.'); print('.'.join(p[-2:]))")
FONTS_ZONE_ID=$(curl -sf -H "Authorization: Bearer $CF_API_TOKEN" \
  "https://api.cloudflare.com/client/v4/zones?name=$FONTS_ZONE_NAME" \
  | python3 -c "import json,sys; r=json.load(sys.stdin); print(r['result'][0]['id']) if r['result'] else exit(1)")
```

If any are blank, stop and surface the issue.

## Phase 3 — Cloudflare Access app + policy (idempotent)

```sh
API="https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID"
H="Authorization: Bearer $CF_API_TOKEN"

# Find One-time PIN IdP UID
OTP_IDP=$(curl -sf -H "$H" "$API/access/identity_providers" \
  | python3 -c "import json,sys; r=json.load(sys.stdin); print(next(p['id'] for p in r['result'] if p['type']=='onetimepin'))")

# Check if an app already exists for HOSTNAME
APP_UID=$(curl -sf -H "$H" "$API/access/apps" \
  | python3 -c "import json,sys; r=json.load(sys.stdin); print(next((a['uid'] for a in r['result'] if a.get('domain','').startswith('${HOSTNAME}')), ''))")

if [ -z "$APP_UID" ]; then
  APP_UID=$(curl -sf -X POST -H "$H" -H "Content-Type: application/json" \
    "$API/access/apps" \
    --data "{\"name\":\"${ACCESS_APP_NAME:-$HOSTNAME}\",\"domain\":\"$HOSTNAME\",\"type\":\"self_hosted\",\"session_duration\":\"${SESSION_DURATION:-24h}\",\"auto_redirect_to_identity\":false,\"app_launcher_visible\":false,\"allowed_idps\":[\"$OTP_IDP\"]}" \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['result']['uid'])")
fi

# Upsert policy
POL_ID=$(curl -sf -H "$H" "$API/access/apps/$APP_UID/policies" \
  | python3 -c "import json,sys; r=json.load(sys.stdin); print(next((p['id'] for p in r['result'] if p['name']=='${ACCESS_POLICY_NAME:-allow-owner}'), ''))")

if [ -z "$POL_ID" ]; then
  curl -sf -X POST -H "$H" -H "Content-Type: application/json" \
    "$API/access/apps/$APP_UID/policies" \
    --data "{\"name\":\"${ACCESS_POLICY_NAME:-allow-owner}\",\"decision\":\"allow\",\"include\":[{\"email\":{\"email\":\"$ALLOWED_EMAIL\"}}],\"precedence\":1}" >/dev/null
fi
```

## Phase 4 — cloudflared ingress + DNS

Edit `~/.cloudflared/config.yml` to add an ingress rule for `$HOSTNAME` above the catch-all 404. **Idempotent**: if the hostname is already present, skip the edit.

```sh
CFG=~/.cloudflared/config.yml
if ! grep -q "hostname: $HOSTNAME$" "$CFG"; then
  # backup
  cp "$CFG" "$CFG.bak.$(date +%s)"
  # insert before catch-all
  python3 - <<PY
import pathlib, yaml
p = pathlib.Path("$CFG")
doc = yaml.safe_load(p.read_text())
catchall = doc['ingress'][-1]
doc['ingress'] = doc['ingress'][:-1] + [
  {'hostname': '$HOSTNAME', 'service': 'http://localhost:${TTYD_PORT:-7681}'},
  catchall,
]
p.write_text(yaml.safe_dump(doc, sort_keys=False))
PY
  cloudflared tunnel --config "$CFG" ingress validate
  launchctl kickstart -k "gui/$(id -u)/com.cloudflare.cloudflared.$TUNNEL_NAME"
fi

# DNS CNAME (idempotent — cloudflared no-ops if it already routes here)
cloudflared tunnel route dns "$TUNNEL_NAME" "$HOSTNAME" 2>&1 | grep -v "already exists" || true
```

If `yaml` python module is missing, `pip install pyyaml` or use `sed` carefully.

## Phase 5 — R2 fonts (WOFF2 + custom domain + CORS)

```sh
# Convert TTF → WOFF2 (idempotent: skip if files exist)
WORKDIR=~/.config/ttyd/fonts
mkdir -p "$WORKDIR"
for variant in regular:Regular bold:Bold; do
  short=${variant%:*}
  long=${variant#*:}
  out="$WORKDIR/jbmono-nerd-$short.woff2"
  if [ ! -f "$out" ]; then
    src="${FONT_DIR:-$HOME/Library/Fonts}/JetBrainsMonoNerdFont-${long}.ttf"
    [ -f "$src" ] || { echo "missing source: $src — download from nerd-fonts releases"; exit 1; }
    tmp="$WORKDIR/.tmp-${short}.ttf"
    command cp "$src" "$tmp"
    woff2_compress "$tmp"
    mv "$WORKDIR/.tmp-${short}.woff2" "$out"
    rm -f "$tmp"
  fi
done

# Create R2 bucket (idempotent)
BUCKET=${R2_BUCKET:-term-fonts}
wrangler r2 bucket list 2>/dev/null | grep -q "^name:.* $BUCKET\$" \
  || wrangler r2 bucket create "$BUCKET"

# Upload (overwrite is fine — content-addressed file names)
wrangler r2 object put "$BUCKET/jbmono-nerd-regular.woff2" \
  --file "$WORKDIR/jbmono-nerd-regular.woff2" \
  --content-type "font/woff2" \
  --cache-control "public, max-age=31536000, immutable" --remote
wrangler r2 object put "$BUCKET/jbmono-nerd-bold.woff2" \
  --file "$WORKDIR/jbmono-nerd-bold.woff2" \
  --content-type "font/woff2" \
  --cache-control "public, max-age=31536000, immutable" --remote

# Attach custom domain (idempotent: check existing list first)
if ! wrangler r2 bucket domain list "$BUCKET" 2>/dev/null | grep -q "$FONTS_HOSTNAME"; then
  wrangler r2 bucket domain add "$BUCKET" \
    --domain "$FONTS_HOSTNAME" --zone-id "$FONTS_ZONE_ID" --min-tls 1.2 --force
fi

# CORS — always upsert from examples/cors.json with HOSTNAME substituted
python3 -c "import json,pathlib; p=pathlib.Path('examples/cors.json'); d=json.loads(p.read_text()); d['rules'][0]['allowed']['origins']=['https://$HOSTNAME']; pathlib.Path('/tmp/r2-cors.json').write_text(json.dumps(d))"
wrangler r2 bucket cors set "$BUCKET" --file /tmp/r2-cors.json
rm /tmp/r2-cors.json
```

## Phase 6 — ttyd LaunchAgent + custom index.html

Build the custom `index.html` (small, external `@font-face`):

```sh
python3 scripts/build-index.py \
  --fonts-host "$FONTS_HOSTNAME" \
  --font-family "${FONT_FAMILY_DISPLAY_NAME:-JetBrainsMono Nerd Font}" \
  --ttyd-port "${TTYD_PORT:-7681}" \
  --out ~/.config/ttyd/index.html
```

The script briefly starts ttyd without `-I` on a throwaway port, fetches its built-in HTML, injects the `<style>@font-face>` + `<link rel=preload>` block, writes to `--out`, and shuts down the throwaway ttyd.

Render the LaunchAgent plist from the template and load it:

```sh
LABEL="com.${USER}.ttyd"
PLIST=~/Library/LaunchAgents/$LABEL.plist
sed \
  -e "s|@@LABEL@@|$LABEL|g" \
  -e "s|@@TTYD_PORT@@|${TTYD_PORT:-7681}|g" \
  -e "s|@@INDEX_PATH@@|$HOME/.config/ttyd/index.html|g" \
  -e "s|@@FONT_FAMILY@@|${FONT_FAMILY_DISPLAY_NAME:-JetBrainsMono Nerd Font}|g" \
  -e "s|@@TMUX_SESSION@@|${TMUX_SESSION:-web}|g" \
  -e "s|@@HOME@@|$HOME|g" \
  -e "s|@@TITLE@@|${HOSTNAME%%.*}|g" \
  examples/com.USER.ttyd.plist.template > "$PLIST"
plutil -lint "$PLIST"

# (re)bootstrap — bootout first if already loaded, ignore failure
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
sleep 1
launchctl print "gui/$(id -u)/$LABEL" | grep -E "state|pid" | head -3
```

## Phase 7 — verify

```sh
# Local ttyd reachable, loopback only
curl -sf -o /dev/null -w "ttyd local: %{http_code}\n" http://127.0.0.1:${TTYD_PORT:-7681}/

# DNS resolves
dig +short "$HOSTNAME" @1.1.1.1 | head -3
dig +short "$FONTS_HOSTNAME" @1.1.1.1 | head -3

# Access challenge fires
curl -sSI --max-time 10 "https://$HOSTNAME" | head -1   # expect HTTP/2 302
curl -sSI --max-time 10 "https://$HOSTNAME" | grep -i ^location | grep -q cloudflareaccess.com \
  && echo "Access ✓" || echo "Access ✗ NOT GATED — investigate before sharing the URL"

# Font CORS preflight
curl -sI -X OPTIONS \
  -H "Origin: https://$HOSTNAME" -H "Access-Control-Request-Method: GET" \
  "https://$FONTS_HOSTNAME/jbmono-nerd-regular.woff2" | grep -i access-control-allow-origin

# Edge cache (second hit should be HIT)
for i in 1 2; do curl -sI "https://$FONTS_HOSTNAME/jbmono-nerd-regular.woff2" | grep -i cf-cache-status; done
```

Report the final URL to the user with: "Open `https://$HOSTNAME` in any browser → email OTP to `$ALLOWED_EMAIL` → tmux session `${TMUX_SESSION:-web}` attaches. Detach with your tmux prefix + `d`."

Remind the user to **revoke the API token** at `https://dash.cloudflare.com/profile/api-tokens` once they've confirmed login works, and offer to delete the local `.env`.

## Rollback (phase R)

Only on explicit user request:

```sh
LABEL="com.${USER}.ttyd"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f ~/Library/LaunchAgents/$LABEL.plist

# Revert cloudflared ingress
CFG=~/.cloudflared/config.yml
python3 - <<PY
import pathlib, yaml
p = pathlib.Path("$CFG"); d = yaml.safe_load(p.read_text())
d['ingress'] = [r for r in d['ingress'] if r.get('hostname') != '$HOSTNAME']
p.write_text(yaml.safe_dump(d, sort_keys=False))
PY
launchctl kickstart -k "gui/$(id -u)/com.cloudflare.cloudflared.$TUNNEL_NAME"

# In the dashboard (manual): delete Access app for $HOSTNAME,
# delete R2 bucket $R2_BUCKET (or just its custom domain),
# delete DNS CNAME for $HOSTNAME if you also want to free the name.
echo "Manual dashboard cleanup remaining: Access app, R2 bucket, DNS CNAME."
```

## Linux notes

Replace LaunchAgent with a systemd user unit:

```ini
# ~/.config/systemd/user/ttyd.service
[Unit]
Description=ttyd web terminal
After=network-online.target
[Service]
ExecStart=/usr/local/bin/ttyd -p 7681 -i 127.0.0.1 -W -I %h/.config/ttyd/index.html \
  -t fontSize=14 -t fontFamily="JetBrainsMono Nerd Font, monospace" \
  /usr/bin/tmux new-session -A -s web
Restart=always
[Install]
WantedBy=default.target
```

`systemctl --user daemon-reload && systemctl --user enable --now ttyd`. Everything else (Cloudflare side) is identical.
