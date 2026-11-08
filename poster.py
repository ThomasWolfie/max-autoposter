#!/usr/bin/env python3
"""
Max's auto-poster: publishes today's post from posts.csv to X, Threads and Telegram.

- Posts every row whose date is today or earlier and that isn't in posted.json yet
  (so a missed day is caught up on the next run).
- Standard library only, no installs needed.
- Configure with environment variables (see README.md). Platforms without credentials are skipped.

Usage:
  python3 poster.py            # post what's due
  python3 poster.py --dry-run  # show what would be posted, post nothing
  python3 poster.py --id 5     # post one specific row now (ignores date)
"""
import base64, csv, datetime, hashlib, hmac, json, mimetypes, os, sys, time, uuid
import urllib.parse, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
POSTS = os.path.join(HERE, "posts.csv")
STATE = os.path.join(HERE, "posted.json")
IMAGES = os.path.join(HERE, "images")
TZ = datetime.timezone(datetime.timedelta(hours=int(os.environ.get("TZ_OFFSET_HOURS", "3"))))  # Moscow by default


# ---------------- helpers ----------------
def http(method, url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read().decode()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {url.split('?')[0]} -> {e.code}: {e.read().decode()[:500]}")


def multipart(fields, files):
    """fields: {name: str}; files: {name: (filename, bytes)} -> (body, content_type)"""
    b = uuid.uuid4().hex
    out = []
    for k, v in fields.items():
        out += [f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()]
    for k, (fn, data) in files.items():
        ct = mimetypes.guess_type(fn)[0] or "application/octet-stream"
        out += [f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{fn}\"\r\n"
                f"Content-Type: {ct}\r\n\r\n".encode(), data, b"\r\n"]
    out.append(f"--{b}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={b}"


def env(name):
    return os.environ.get(name, "").strip()


# ---------------- X (Twitter) ----------------
def x_enabled():
    return all(env(k) for k in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET"))


def x_auth_header(method, url, params=None):
    """OAuth 1.0a user-context signature. JSON/multipart bodies are not signed."""
    q = lambda s: urllib.parse.quote(str(s), safe="~")
    oauth = {
        "oauth_consumer_key": env("X_API_KEY"),
        "oauth_nonce": uuid.uuid4().hex,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": env("X_ACCESS_TOKEN"),
        "oauth_version": "1.0",
    }
    allp = {**(params or {}), **oauth}
    pstr = "&".join(f"{q(k)}={q(v)}" for k, v in sorted(allp.items()))
    base = "&".join([method.upper(), q(url), q(pstr)])
    key = f"{q(env('X_API_SECRET'))}&{q(env('X_ACCESS_SECRET'))}"
    oauth["oauth_signature"] = base64.b64encode(hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    return "OAuth " + ", ".join(f'{q(k)}="{q(v)}"' for k, v in sorted(oauth.items()))


def x_weighted_len(s):
    # X counts most non-Latin chars and emoji as 2
    return sum(1 if ord(c) < 0x1100 else 2 for c in s)


def x_split(text, limit=275):
    """Split long text into a thread on paragraph breaks."""
    if x_weighted_len(text) <= limit:
        return [text]
    parts, cur = [], ""
    for para in text.split("\n\n"):
        cand = (cur + "\n\n" + para).strip()
        if x_weighted_len(cand) <= limit:
            cur = cand
        else:
            if cur:
                parts.append(cur)
            cur = para
    parts.append(cur)
    return parts


def x_upload(path):
    url = "https://api.x.com/2/media/upload"
    with open(path, "rb") as f:
        body, ct = multipart({"media_category": "tweet_image"}, {"media": (os.path.basename(path), f.read())})
    r = http("POST", url, body, {"Authorization": x_auth_header("POST", url), "Content-Type": ct})
    return (r.get("data") or {}).get("id") or r.get("media_id_string")


def x_post(text, image):
    url = "https://api.x.com/2/tweets"
    media_id = x_upload(image) if image else None
    reply_to, first = None, None
    for i, chunk in enumerate(x_split(text)):
        payload = {"text": chunk}
        if i == 0 and media_id:
            payload["media"] = {"media_ids": [media_id]}
        if reply_to:
            payload["reply"] = {"in_reply_to_tweet_id": reply_to}
        r = http("POST", url, json.dumps(payload).encode(),
                 {"Authorization": x_auth_header("POST", url), "Content-Type": "application/json"})
        reply_to = r["data"]["id"]
        first = first or reply_to
    return first


# ---------------- Threads ----------------
def threads_enabled():
    return bool(env("THREADS_ACCESS_TOKEN"))


def threads_post(text, image_name):
    base = "https://graph.threads.net/v1.0"
    uid = env("THREADS_USER_ID") or "me"
    tok = env("THREADS_ACCESS_TOKEN")
    params = {"text": text[:500], "access_token": tok}
    if image_name:
        img_base = env("IMAGE_BASE_URL")
        if not img_base:
            raise RuntimeError("IMAGE_BASE_URL is not set: Threads needs a public URL for images")
        params.update(media_type="IMAGE", image_url=img_base.rstrip("/") + "/" + image_name)
    else:
        params["media_type"] = "TEXT"
    c = http("POST", f"{base}/{uid}/threads", urllib.parse.urlencode(params).encode())
    time.sleep(30 if image_name else 5)  # Meta asks to give the container time to process
    r = http("POST", f"{base}/{uid}/threads_publish",
             urllib.parse.urlencode({"creation_id": c["id"], "access_token": tok}).encode())
    return r["id"]


def threads_refresh_token():
    """Long-lived Threads tokens last ~60 days. Prints a refreshed one."""
    r = http("GET", "https://graph.threads.net/refresh_access_token?" + urllib.parse.urlencode(
        {"grant_type": "th_refresh_token", "access_token": env("THREADS_ACCESS_TOKEN")}))
    print("New token (save it as THREADS_ACCESS_TOKEN):", r.get("access_token"))
    print("Expires in days:", int(r.get("expires_in", 0)) // 86400)


# ---------------- Telegram ----------------
def telegram_enabled():
    return bool(env("TELEGRAM_BOT_TOKEN") and env("TELEGRAM_CHANNEL"))


def telegram_post(text, image):
    api = f"https://api.telegram.org/bot{env('TELEGRAM_BOT_TOKEN')}"
    chat = env("TELEGRAM_CHANNEL")
    if image and len(text) <= 1024:
        with open(image, "rb") as f:
            body, ct = multipart({"chat_id": chat, "caption": text}, {"photo": (os.path.basename(image), f.read())})
        r = http("POST", f"{api}/sendPhoto", body, {"Content-Type": ct})
    else:
        r = http("POST", f"{api}/sendMessage", urllib.parse.urlencode({"chat_id": chat, "text": text}).encode())
    return str(r["result"]["message_id"])


PLATFORMS = {
    "x": (x_enabled, lambda t, img, name: x_post(t, img)),
    "threads": (threads_enabled, lambda t, img, name: threads_post(t, name)),
    "telegram": (telegram_enabled, lambda t, img, name: telegram_post(t, img)),
}


# ---------------- main ----------------
def main():
    args = sys.argv[1:]
    if "--refresh-threads-token" in args:
        return threads_refresh_token()
    dry = "--dry-run" in args
    only_id = args[args.index("--id") + 1] if "--id" in args else None

    state = json.load(open(STATE)) if os.path.exists(STATE) else {}
    today = datetime.datetime.now(TZ).date()
    rows = list(csv.DictReader(open(POSTS, encoding="utf-8")))
    failures = 0

    for row in rows:
        pid = row["id"]
        if only_id and pid != only_id:
            continue
        if not only_id and datetime.date.fromisoformat(row["date"]) > today:
            continue
        done = state.setdefault(pid, {})
        img_name = row.get("image", "").strip()
        img_path = os.path.join(IMAGES, img_name) if img_name else None
        for p in [p.strip() for p in row["platforms"].split(",") if p.strip()]:
            if p in done or p not in PLATFORMS:
                continue
            enabled, send = PLATFORMS[p]
            if not enabled():
                print(f"[skip] #{pid} {p}: no credentials")
                continue
            if dry:
                print(f"[dry-run] #{pid} {row['date']} -> {p} (image: {img_name or 'none'})\n{row['text']}\n")
                continue
            try:
                done[p] = send(row["text"], img_path, img_name)
                print(f"[ok] #{pid} -> {p}: {done[p]}")
            except Exception as e:
                failures += 1
                print(f"[error] #{pid} -> {p}: {e}")
        if not done:
            state.pop(pid)

    if not dry:
        json.dump(state, open(STATE, "w"), indent=2)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
