#!/usr/bin/env python3
"""Harvest ttyd's built-in index.html and inject @font-face + preload.

Usage:
  python3 build-index.py --fonts-host fonts.example.com \
      --font-family "JetBrainsMono Nerd Font" \
      --ttyd-port 7681 --out ~/.config/ttyd/index.html

If ttyd isn't already listening on --ttyd-port, the script briefly starts a
throwaway ttyd (without -I) to harvest its bundled HTML, then shuts it down.
"""
import argparse, os, pathlib, signal, socket, subprocess, sys, time, urllib.request


def ttyd_running(port: int) -> bool:
    s = socket.socket()
    s.settimeout(0.3)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def harvest_html(port: int) -> str:
    """Return ttyd's built-in index.html, spinning up a temp ttyd if needed."""
    spawned = None
    if not ttyd_running(port):
        spawned = subprocess.Popen(
            ["ttyd", "-p", str(port), "-i", "127.0.0.1", "-W", "-o",
             "/bin/sh", "-c", "sleep 60"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        # Wait up to 3s for it to come up
        for _ in range(30):
            if ttyd_running(port):
                break
            time.sleep(0.1)
        else:
            spawned.terminate()
            raise SystemExit("could not start ttyd")
    try:
        return urllib.request.urlopen(
            f"http://127.0.0.1:{port}/", timeout=5
        ).read().decode("utf-8", errors="replace")
    finally:
        if spawned:
            spawned.send_signal(signal.SIGTERM)
            try:
                spawned.wait(timeout=2)
            except subprocess.TimeoutExpired:
                spawned.kill()


def inject(html: str, fonts_host: str, family: str) -> str:
    marker = "<head>"
    idx = html.find(marker)
    if idx < 0:
        raise SystemExit("could not find <head>")
    style = (
        "<style>"
        f'@font-face{{font-family:"{family}";font-style:normal;font-weight:400;'
        f'font-display:swap;src:url("https://{fonts_host}/jbmono-nerd-regular.woff2") format("woff2");}}'
        f'@font-face{{font-family:"{family}";font-style:normal;font-weight:700;'
        f'font-display:swap;src:url("https://{fonts_host}/jbmono-nerd-bold.woff2") format("woff2");}}'
        "</style>"
        f'<link rel="preload" as="font" type="font/woff2" crossorigin '
        f'href="https://{fonts_host}/jbmono-nerd-regular.woff2">'
        f'<link rel="preload" as="font" type="font/woff2" crossorigin '
        f'href="https://{fonts_host}/jbmono-nerd-bold.woff2">'
    )
    pos = idx + len(marker)
    return html[:pos] + style + html[pos:]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fonts-host", required=True)
    ap.add_argument("--font-family", required=True)
    ap.add_argument("--ttyd-port", type=int, default=7681)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    out_path = pathlib.Path(os.path.expanduser(args.out))
    out_path.parent.mkdir(parents=True, exist_ok=True)

    html = harvest_html(args.ttyd_port)
    final = inject(html, args.fonts_host, args.font_family)
    out_path.write_text(final)
    print(f"wrote {out_path} ({len(final)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
