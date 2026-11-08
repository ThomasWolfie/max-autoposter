# Max's auto-poster

Posts one tip a day to **X**, **Threads** and a **Telegram channel** from `posts.csv`.
It runs free on GitHub Actions at 10:00 Moscow time. You don't need a server.

## What's inside
- `posts.csv`: 30 days of posts (Nov 10 – Dec 9, 2026). Edit it in Excel or Google Sheets and keep the columns.
  `platforms` can be any mix of `x,threads,telegram`. `image` is a file name in `images/` or empty.
- `images/`: 8 ready-made cards (1080×1350).
- `poster.py`: the bot. It uses Python's standard library only.
- `.github/workflows/post.yml`: the daily schedule.
- `posted.json`: created automatically. It records what's already published so nothing gets posted twice.
  A missed day gets caught up on the next run.

## Setup (about 30–40 minutes, one time)

### 1. GitHub
1. Create a **public** repo and upload all these files, including the `.github` folder.
   It has to be public because Threads fetches images from a public URL. The repo URL becomes the image host.
2. Go to repo → Settings → Secrets and variables → Actions → *New repository secret* and add the keys below.

### 2. Telegram (easiest, free)
1. In Telegram, message **@BotFather** → `/newbot` → copy the token → secret `TELEGRAM_BOT_TOKEN`.
2. Create your channel, add the bot as an **admin** who can post.
3. Secret `TELEGRAM_CHANNEL` = `@yourchannelname`.

### 3. Threads
1. Go to developers.facebook.com → create an app → add the **Threads API** use case.
2. Give it the `threads_basic` and `threads_content_publish` permissions and add your Threads account as a tester.
3. Generate a **long-lived** access token → secret `THREADS_ACCESS_TOKEN`
   (optional: `THREADS_USER_ID`, otherwise `me` is used).
4. The token lasts about 60 days. Before it expires, run
   `THREADS_ACCESS_TOKEN=... python3 poster.py --refresh-threads-token` and update the secret.

### 4. X
1. Go to developer.x.com → create a project and app → set the app permissions to **Read and write**.
2. Generate the *API Key & Secret* and the *Access Token & Secret* (they must be generated **after** you set Read and write).
3. Add the secrets `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_SECRET`.
4. X bills the API per post. Add a few dollars of credits and set a spending limit. **Don't put links in X posts**,
   because posts with links cost much more through the API. Put your Telegram link in your X bio instead.

Platforms with no secrets set are skipped, so you can start with Telegram only.

### 5. Test
Actions tab → *Daily post* → **Run workflow**. Nothing is due before Nov 10, so the first real post goes out that day.
To test sooner, run it locally on one post:
```
export TELEGRAM_BOT_TOKEN=... TELEGRAM_CHANNEL=@...
python3 poster.py --dry-run          # preview
python3 poster.py --id 2             # actually post row 2 now
```

## Adding the next month
Add rows to `posts.csv` with new dates. Put new images in `images/` and reference them by name.

## Before you publish
Read every post once and adjust any detail that doesn't match your own experience. They're written in your voice,
so they should be true for you. Every 3–4 days, reply to comments by hand: replies are what turn followers into leads.
