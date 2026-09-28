# -*- coding: utf-8 -*-
"""Public HTTPS link for PashuAarogya — phones need NO shared Wi-Fi.

Prefers **ngrok with a reserved domain** (permanent URL; the free plan gives
exactly one static domain), falls back to a **Cloudflare quick tunnel**
(random URL each run, no account). HTTPS also unlocks the microphone
(voice assistant), camera and PWA install on Android Chrome, which plain
http://192.168.x.x never gets.

    python tunnel.py            (run.bat starts this automatically)

Config (all optional):
    PASHU_NGROK          path to ngrok.exe
    PASHU_TUNNEL_DOMAIN  reserved ngrok domain
    PASHU_PORT           local port (default 8000)
Defaults reuse the PashuPehchaan setup: BreedVision18/.tools/ngrok.exe and
BreedVision18/tunnel.json {"domain": "..."}.
"""
import json, os, re, shutil, subprocess, sys, time, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PASHU_PORT", "8000"))
OUT = os.path.join(ROOT, "backend", "public_url.txt")
OLD_PROJECT = r"C:\Users\admin\Desktop\BreedVision18"


def find_ngrok():
    for c in (os.environ.get("PASHU_NGROK"), shutil.which("ngrok"),
              os.path.join(OLD_PROJECT, ".tools", "ngrok.exe"),
              os.path.join(ROOT, ".tools", "ngrok.exe")):
        if c and os.path.exists(c):
            return c
    return None


def reserved_domain():
    d = os.environ.get("PASHU_TUNNEL_DOMAIN")
    if d:
        return d
    for p in (os.path.join(ROOT, "tunnel.json"), os.path.join(OLD_PROJECT, "tunnel.json")):
        try:
            with open(p, encoding="utf-8") as fh:
                return json.load(fh).get("domain")
        except Exception:
            pass
    return None


def ngrok_public_url():
    try:
        with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=2) as r:
            t = json.loads(r.read().decode()).get("tunnels", [])
        https = [x["public_url"] for x in t if x.get("public_url", "").startswith("https")]
        return (https or [x["public_url"] for x in t] or [None])[0]
    except Exception:
        return None


def write_url(url):
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(url)


def clear_url():
    try:
        os.remove(OUT)
    except OSError:
        pass


def run_ngrok(exe, domain):
    # free plan = one agent session; leftovers from earlier runs block the domain
    subprocess.run(["taskkill", "/IM", "ngrok.exe", "/F"], capture_output=True)
    time.sleep(1)
    args = [exe, "http", str(PORT), "--log", "stdout", "--log-format", "json"]
    if domain:
        args += ["--domain", domain]
    # log to a file, never a pipe: ngrok logs every request and a full pipe
    # buffer would stall the agent
    logp = os.path.join(ROOT, "backend", "ngrok.log")
    logf = open(logp, "w", encoding="utf-8")
    p = subprocess.Popen(args, stdout=logf, stderr=subprocess.STDOUT, text=True)
    url = None
    for _ in range(40):
        time.sleep(0.75)
        url = ngrok_public_url()
        if url:
            break
        if p.poll() is not None:
            try:
                out = open(logp, encoding="utf-8").read()
            except OSError:
                out = ""
            print("ngrok exited:\n" + out[-1500:])
            return None
    if not url:
        print("ngrok did not report a tunnel in time")
        p.terminate()
        return None
    write_url(url)
    banner(url, "ngrok" + (" · reserved domain (permanent)" if domain else " · random URL"))
    try:
        p.wait()
    finally:
        clear_url()
    return url


def run_cloudflared():
    exe = shutil.which("cloudflared") or os.path.join(ROOT, ".tools", "cloudflared.exe")
    if not os.path.exists(exe):
        print("No ngrok and no cloudflared found.\n"
              "  Option A: put ngrok.exe at pashuraksha/.tools/ngrok.exe (https://ngrok.com/download)\n"
              "  Option B: put cloudflared.exe at pashuraksha/.tools/cloudflared.exe\n"
              "            (https://github.com/cloudflare/cloudflared/releases/latest)")
        return None
    p = subprocess.Popen([exe, "tunnel", "--url", f"http://127.0.0.1:{PORT}", "--no-autoupdate"],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    url = None
    for line in p.stdout:
        m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
        if m:
            url = m.group(0)
            write_url(url)
            banner(url, "Cloudflare quick tunnel · URL changes each run")
            break
    if not url:
        return None
    try:
        p.wait()
    finally:
        clear_url()
    return url


def banner(url, how):
    print("\n" + "=" * 64)
    print("  PashuAarogya is PUBLIC:  " + url)
    print("  " + how)
    print("  Open on any phone (mobile data OK). First visit may show a one-time")
    print("  ngrok 'Visit Site' page - tap it. Then Chrome > Add to Home screen.")
    print("  The login page QR now points here. Ctrl+C to stop.")
    print("=" * 64 + "\n", flush=True)


if __name__ == "__main__":
    ng = find_ngrok()
    if ng:
        if run_ngrok(ng, reserved_domain()) is None:
            print("ngrok failed - trying cloudflared ...")
            run_cloudflared()
    else:
        run_cloudflared()
