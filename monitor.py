#!/usr/bin/env python3
"""X (Twitter) + Telegram keyword monitor.

Watches a handful of X accounts (via the official X API) and a configurable
list of Telegram groups/channels (read as a logged-in user account via
MTProto/telethon) for messages containing configured keywords, and forwards
matches to a Telegram chat via a bot.

Intended to run a few times a day from a GitHub Actions scheduled workflow.
See README.md for setup instructions.
"""

import json
import os
import sys
import time

import requests
import tweepy
from telethon.sessions import StringSession
from telethon.sync import TelegramClient
from telethon.tl.types import MessageService

# ---------------------------------------------------------------------------
# Config: sources and keywords
# ---------------------------------------------------------------------------
# Empty keyword list = match everything from that source.
# Matching is a case-insensitive substring match on the item text.

X_TARGETS = {
    "DailyDarkWeb": ["Singapore"],
    "VECERTRadar": ["Singapore"],  # verify exact spelling at build time
    "DarkWebInformer": ["Singapore"],
}

# Telegram groups/channels to watch. The operator's USER account (the one
# that generated TELEGRAM_SESSION via gen_session.py) must already be a
# member of every entry here. Keys may be:
#   - a public @username (string, e.g. "@some_public_group")
#   - a numeric chat ID (int, e.g. -1001234567890), for private chats
# Fill in real targets below; these are placeholders.
TELEGRAM_TARGETS = {
    "@replace_with_group_username_1": ["Singapore"],
    "@replace_with_group_username_2": ["Singapore"],
    -1001234567890: ["Singapore"],  # example numeric chat ID placeholder
}

STATE_PATH = "state.json"

REQUIRED_ENV_VARS = [
    "X_BEARER_TOKEN",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "TELEGRAM_API_ID",
    "TELEGRAM_API_HASH",
    "TELEGRAM_SESSION",
]

X_BASELINE_COUNT = 5
X_FETCH_COUNT = 100
TELEGRAM_BASELINE_COUNT = 5
TELEGRAM_FETCH_LIMIT = 200

MATCH_ALL = "__MATCH_ALL__"


# ---------------------------------------------------------------------------
# Env / state helpers
# ---------------------------------------------------------------------------
def load_env():
    missing = [v for v in REQUIRED_ENV_VARS if not os.environ.get(v)]
    if missing:
        print(f"ERROR: missing required environment variable(s): {', '.join(missing)}")
        sys.exit(1)
    return {v: os.environ[v] for v in REQUIRED_ENV_VARS}


def load_state():
    if not os.path.exists(STATE_PATH):
        state = {}
    else:
        with open(STATE_PATH) as f:
            state = json.load(f)
    state.setdefault("x", {})
    state["x"].setdefault("user_ids", {})
    state["x"].setdefault("last_seen", {})
    state.setdefault("telegram", {})
    state["telegram"].setdefault("last_seen", {})
    return state


def save_state(state):
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2, sort_keys=True)
        f.write("\n")


# ---------------------------------------------------------------------------
# Shared matching + notification
# ---------------------------------------------------------------------------
def match(text, keywords):
    """Return the matched keyword, MATCH_ALL (if keywords is empty), or None."""
    if not text:
        return None
    if not keywords:
        return MATCH_ALL
    lowered = text.lower()
    for keyword in keywords:
        if keyword.lower() in lowered:
            return keyword
    return None


def notify(env, source, keyword, text, link):
    bot_token = env["TELEGRAM_BOT_TOKEN"]
    chat_id = env["TELEGRAM_CHAT_ID"]
    keyword_label = "(any)" if keyword == MATCH_ALL else keyword

    lines = [f"Source: {source}", f"Keyword: {keyword_label}", "", text.strip()]
    if link:
        lines.append("")
        lines.append(link)
    message = "\n".join(lines)

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            data={"chat_id": chat_id, "text": message},
            timeout=15,
        )
        if resp.status_code != 200:
            print(f"[notify] Failed to send alert ({resp.status_code}): {resp.text}")
    except requests.RequestException as e:
        print(f"[notify] Failed to send alert: {e}")

    time.sleep(1)


# ---------------------------------------------------------------------------
# X (Twitter) source
# ---------------------------------------------------------------------------
def fetch_x_user_id(client, handle):
    """Isolated lookup call. Swap the provider here if needed later."""
    user = client.get_user(username=handle)
    if user.data is None:
        return None
    return str(user.data.id)


def fetch_x_user_tweets(client, user_id, since_id=None, max_results=X_FETCH_COUNT):
    """Isolated fetch call. Swap the provider here if needed later."""
    response = client.get_users_tweets(
        id=user_id,
        since_id=since_id,
        max_results=max_results,
        tweet_fields=["created_at"],
    )
    return response.data or []


def check_x_sources(state, env):
    client = tweepy.Client(bearer_token=env["X_BEARER_TOKEN"], wait_on_rate_limit=True)

    for handle, keywords in X_TARGETS.items():
        try:
            user_id = state["x"]["user_ids"].get(handle)
            if not user_id:
                user_id = fetch_x_user_id(client, handle)
                if not user_id:
                    print(f"[x] WARNING: could not resolve handle @{handle} (unresolvable / misspelled?) - skipping.")
                    continue
                state["x"]["user_ids"][handle] = user_id
                save_state(state)

            last_id = state["x"]["last_seen"].get(handle)
            is_first_run = last_id is None

            tweets = fetch_x_user_tweets(
                client,
                user_id,
                since_id=last_id,
                max_results=X_BASELINE_COUNT if is_first_run else X_FETCH_COUNT,
            )

            if not tweets:
                continue

            tweets = list(reversed(tweets))  # API returns newest-first; we want oldest-first
            newest_id = max(int(t.id) for t in tweets)

            if is_first_run:
                print(f"[x] First run for @{handle}: recording baseline tweet {newest_id}, no alerts sent.")
            else:
                for tweet in tweets:
                    keyword = match(tweet.text, keywords)
                    if keyword:
                        link = f"https://x.com/{handle}/status/{tweet.id}"
                        notify(env, f"X / @{handle}", keyword, tweet.text, link)

            state["x"]["last_seen"][handle] = str(newest_id)
            save_state(state)

        except Exception as e:
            print(f"[x] ERROR processing @{handle}: {e}")
            continue


# ---------------------------------------------------------------------------
# Telegram-read source (user account via MTProto)
# ---------------------------------------------------------------------------
def check_telegram_sources(state, env):
    api_id = int(env["TELEGRAM_API_ID"])
    api_hash = env["TELEGRAM_API_HASH"]
    session_str = env["TELEGRAM_SESSION"]

    client = TelegramClient(StringSession(session_str), api_id, api_hash)
    client.connect()
    try:
        if not client.is_user_authorized():
            print("[telegram] ERROR: session is not authorized. Regenerate TELEGRAM_SESSION with gen_session.py.")
            return

        for target, keywords in TELEGRAM_TARGETS.items():
            target_key = str(target)
            try:
                entity = client.get_entity(target)
            except Exception as e:
                print(f"[telegram] WARNING: could not resolve {target_key} (not a member / invalid?) - skipping. ({e})")
                continue

            try:
                last_id = state["telegram"]["last_seen"].get(target_key)
                is_first_run = last_id is None

                if is_first_run:
                    messages = list(client.iter_messages(entity, limit=TELEGRAM_BASELINE_COUNT))
                else:
                    messages = list(
                        client.iter_messages(entity, min_id=last_id, limit=TELEGRAM_FETCH_LIMIT, reverse=True)
                    )

                messages = [m for m in messages if not isinstance(m, MessageService)]
                if not messages:
                    continue

                newest_id = max(m.id for m in messages)
                username = getattr(entity, "username", None)
                title = getattr(entity, "title", None) or username or target_key
                source_name = f"Telegram / {title}"

                if is_first_run:
                    print(f"[telegram] First run for {target_key}: recording baseline message {newest_id}, no alerts sent.")
                else:
                    # iter_messages(..., reverse=True) already yields oldest-first
                    for msg in messages:
                        text = msg.message
                        if not text:
                            continue
                        keyword = match(text, keywords)
                        if keyword:
                            link = f"https://t.me/{username}/{msg.id}" if username else None
                            notify(env, source_name, keyword, text, link)

                state["telegram"]["last_seen"][target_key] = newest_id
                save_state(state)

            except Exception as e:
                print(f"[telegram] ERROR processing {target_key}: {e}")
                continue
    finally:
        client.disconnect()


# ---------------------------------------------------------------------------
def main():
    env = load_env()
    state = load_state()

    try:
        check_x_sources(state, env)
    except Exception as e:
        print(f"[x] Unexpected top-level error: {e}")

    try:
        check_telegram_sources(state, env)
    except Exception as e:
        print(f"[telegram] Unexpected top-level error: {e}")

    save_state(state)


if __name__ == "__main__":
    main()
