# liveevil — X + Telegram keyword monitor

Watches a few X (Twitter) accounts and a configurable list of Telegram
groups/channels for the keyword **"Singapore"** (case-insensitive) and sends
an alert to a Telegram chat via a bot. Runs on a GitHub Actions schedule
(~6x/day) — no server required.

## How it works

- **X accounts** are read via the official X API v2 (`tweepy`), using the
  user-timeline endpoint (`get_users_tweets`).
- **Telegram groups/channels** are read by logging in as a real Telegram
  *user* account via MTProto (`telethon`). Bots cannot read messages in
  third-party groups, so this is unavoidable — the user account must already
  be a member of every group/channel being monitored. The app only reads
  messages; it never joins groups, scrapes members, or sends messages to
  monitored chats.
- **Alerts** are delivered by a separate Telegram *bot* (`TELEGRAM_BOT_TOKEN`)
  posting to a single chat (`TELEGRAM_CHAT_ID`) via the Bot API.
- State (last-seen tweet/message ID per target, and resolved X user IDs) is
  stored in `state.json`, committed back to the repo by the workflow after
  each run. No database.

On the very first run for any target there's no stored last-seen ID yet, so
the app records a baseline (the latest few items) and sends **no alerts**.
Alerts begin from the second run onward.

## Setup

### 1. Create the alert bot

1. Message [@BotFather](https://t.me/BotFather) on Telegram, run `/newbot`,
   and follow the prompts. Save the bot token it gives you — this is
   `TELEGRAM_BOT_TOKEN`.
2. Decide where alerts should go (a DM with the bot, or a group/channel the
   bot is added to as admin). Send the bot/chat a message, then get the chat
   ID, e.g. by visiting
   `https://api.telegram.org/bot<TOKEN>/getUpdates` and reading
   `message.chat.id` from the response. This is `TELEGRAM_CHAT_ID`.

### 2. Get an X API bearer token

1. Apply for/create a project & app at the
   [X Developer Portal](https://developer.x.com/).
2. Generate a **Bearer Token** (App-only auth is enough for
   `get_users_tweets`). This is `X_BEARER_TOKEN`.

### 3. Get Telegram API credentials (for reading, as your user account)

1. Go to [my.telegram.org](https://my.telegram.org), log in with the phone
   number of the account that has already joined the groups you want to
   monitor, and create an app under "API development tools".
2. Note the `api_id` and `api_hash` — these are `TELEGRAM_API_ID` and
   `TELEGRAM_API_HASH`.

### 4. Generate a session string (run locally, not in CI)

`gen_session.py` is a one-off interactive helper — run it on your own
machine, never in GitHub Actions:

```bash
pip install -r requirements.txt
python gen_session.py
```

It will prompt for your `api_id`/`api_hash`, then your phone number, login
code, and 2FA password (if set), and finally print a **StringSession**.
Treat that string like a password:

- Never commit it to the repo.
- Never paste it anywhere except the `TELEGRAM_SESSION` GitHub secret below.

### 5. Join the groups/channels you want to monitor

Using the *same Telegram user account* you just generated a session for,
join (or make sure you've already joined) every group/channel you want to
watch. The app will not auto-join anything — if the account isn't a member,
that target is skipped with a warning.

Then edit `TELEGRAM_TARGETS` in `monitor.py` with the real `@username`s or
numeric chat IDs:

```python
TELEGRAM_TARGETS = {
    "@some_public_group": ["Singapore"],
    "@another_channel": ["Singapore"],
    -1001234567890: ["Singapore"],  # numeric chat ID, for private chats
}
```

(For private groups without a public username, get the numeric chat ID from
any Telegram API/bot tooling you're comfortable with, or from telethon's
`dialogs` list.)

### 6. Push to GitHub and add secrets

Push this repo to GitHub, then under **Settings → Secrets and variables →
Actions**, add:

| Secret | Value |
|---|---|
| `X_BEARER_TOKEN` | X API bearer token |
| `TELEGRAM_BOT_TOKEN` | Alert bot token from BotFather |
| `TELEGRAM_CHAT_ID` | Chat ID alerts are sent to |
| `TELEGRAM_API_ID` | From my.telegram.org |
| `TELEGRAM_API_HASH` | From my.telegram.org |
| `TELEGRAM_SESSION` | StringSession printed by `gen_session.py` |

### 7. Run it

Go to the **Actions** tab → **Keyword Monitor** → **Run workflow** to trigger
a manual run (`workflow_dispatch`). The first run for each target establishes
a baseline and sends no alerts; `state.json` is committed back automatically
if it changed. After that, the workflow runs on its own schedule (~6x/day,
see `.github/workflows/monitor.yml` for the cron times in Singapore time).

## Configuration

Edit the dictionaries near the top of `monitor.py`:

- `X_TARGETS`: `{handle: [keywords]}`. An empty keyword list matches every
  tweet from that account.
- `TELEGRAM_TARGETS`: `{username_or_chat_id: [keywords]}`. Same matching
  rule.

Matching is a case-insensitive substring match on the tweet/message text
(including media captions).

## Notes / limitations

- Not real-time — content may sit for a few hours between runs by design.
- A failure on one target (misspelled handle, not-a-member group, rate
  limit) is logged and skipped; it never aborts the whole run.
- The X handle `@VECERTRadar` should be double-checked for exact spelling
  before relying on alerts from it — if it can't be resolved, the run logs a
  loud warning and continues with the other targets.
