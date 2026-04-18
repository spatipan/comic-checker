import json
import argparse
import httpx
import yaml
import os
import re
from dotenv import load_dotenv
from pathlib import Path
import logging
import time
from curl_cffi import requests as cffi_requests

try:
    from src.prober import run_probe
except ModuleNotFoundError:
    from prober import run_probe

load_dotenv()

# -- Configuration --
STATE_FILE = Path(__file__).parent / "state.json"
SUBSCRIPTION_FILE = Path(__file__).parent.parent / "config" / "subscription.yaml"
TG_TOKEN = os.getenv("TG_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

logger = logging.getLogger(__name__)
CHAPTER_RE = re.compile(r"chapter-(\d+)")

def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE, "r") as f:
            raw_state = json.load(f)
            logger.info("state_loaded path=%s entries=%s", STATE_FILE, len(raw_state))
            return raw_state

    logger.info("state_missing path=%s", STATE_FILE)
    return {}

def save_state(state) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

    logger.info("state_saved path=%s entries=%s", STATE_FILE, len(state))

def load_subscription() -> list:
    with open(SUBSCRIPTION_FILE, "r") as f:
        subscription = yaml.safe_load(f) or {}

    mangas = [manga for manga in subscription.get("subscription", []) if manga.get("name") and manga.get("url")]
    logger.info("subscriptions_loaded path=%s count=%s", SUBSCRIPTION_FILE, len(mangas))
    logger.debug("subscriptions=%s", mangas)
    return mangas

def check_chapter(manga, chapter, strategy) -> bool:
    url = manga["url"].format(chapter=chapter)
    check_method = strategy.get("method", "unknown")

    try:
        if check_method == "title_match":
            response = cffi_requests.get(
                url,
                allow_redirects=True,
                timeout=10,
                impersonate="chrome136",
                headers={"referer": strategy.get("referer")},
            )
            logger.debug(
                "chapter_checked method=title_match url=%s status_code=%s title_match=%s",
                url,
                response.status_code,
                f"Chapter {chapter}" in response.text[:5000],
            )
            return response.status_code == 200 and f"Chapter {chapter}" in response.text[:5000]

        if check_method == "keyword":
            response = cffi_requests.get(
                url,
                allow_redirects=True,
                timeout=10,
                impersonate="chrome136",
                headers={"referer": strategy.get("referer")},
            )
            keywords = strategy.get("keywords", [])
            text = response.text.lower()
            return response.status_code == 200 and not any(keyword in text for keyword in keywords)

        if check_method == "content_length":
            response = cffi_requests.get(
                url,
                allow_redirects=True,
                timeout=10,
                impersonate="chrome136",
                headers={"referer": strategy.get("referer")},
            )
            low, high = strategy.get("expected_length_range", [0, float("inf")])
            return response.status_code == 200 and low <= len(response.text) <= high

        if check_method == "redirect":
            response = httpx.get(
                url,
                follow_redirects=True,
                timeout=10,
            )
            return response.status_code == 200 and str(response.url) != strategy.get("redirect_target")

        if check_method == "unknown":
            return False

        response = httpx.head(
            url,
            follow_redirects=True,
            timeout=10,
        )
        logger.debug(
            "chapter_checked method=HEAD url=%s status_code=%s",
            url,
            response.status_code,
        )

        if response.status_code == 200:
            return True

        if response.status_code in {403, 405}:
            fallback = httpx.get(
                url,
                follow_redirects=True,
                timeout=10,
            )
            logger.debug(
                "chapter_checked method=GET url=%s status_code=%s",
                url,
                fallback.status_code,
            )
            return fallback.status_code == 200

        return False
    except (httpx.RequestError, cffi_requests.RequestsError) as exc:
        logger.error("chapter_check_failed method=%s url=%s error=%s", check_method, url, exc)
        return False


def get_redirect_latest_chapter(manga, last_chapter, strategy):
    url = manga["url"].format(chapter=last_chapter)
    try:
        if strategy.get("use_cffi"):
            response = cffi_requests.get(
                url,
                allow_redirects=True,
                timeout=10,
                impersonate="chrome136",
                headers={"referer": strategy.get("referer")},
            )
            final_url = str(response.url)
            status_code = response.status_code
        else:
            response = httpx.get(
                url,
                follow_redirects=True,
                timeout=10,
            )
            final_url = str(response.url)
            status_code = response.status_code

        match = CHAPTER_RE.search(final_url)
        latest_chapter = int(match.group(1)) if match else None
        logger.debug(
            "chapter_checked method=redirect_latest url=%s status_code=%s final_url=%s latest_chapter=%s",
            url,
            status_code,
            final_url,
            latest_chapter,
        )
        return latest_chapter
    except (httpx.RequestError, cffi_requests.RequestsError) as exc:
        logger.error("chapter_check_failed method=redirect_latest url=%s error=%s", url, exc)
        return None

def notify(message: str) -> None:
    if not TG_TOKEN or not TG_CHAT_ID:
        logger.warning("notify_skipped reason=missing_telegram_env")
        return

    httpx.post(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        data={"chat_id": TG_CHAT_ID, "text": message},
    )
    logger.info("notification_sent channel=telegram")


def run_check() -> None:
    logger.info("checker_started")
    state = load_state()
    subscription = load_subscription()

    for manga in subscription:
        logger.debug(
            "subscription_target name=%s url_template=%s",
            manga.get("name"),
            manga.get("url"),
        )

    for manga in subscription:
        name = manga["name"]
        notify_on_new = manga.get("notify", False)
        state_entry = state.get(name)
        if not state_entry or not state_entry.get("strategy"):
            logger.warning("series_skipped_missing_strategy name=%s", name)
            continue

        last_chapter = int(state_entry.get("last_chapter", 0))
        strategy = state_entry["strategy"]
        next_chapter = last_chapter + 1

        logger.info("series_check_started name=%s next_chapter=%s", name, next_chapter)

        if strategy.get("method") == "redirect_latest":
            latest_chapter = get_redirect_latest_chapter(manga, last_chapter, strategy)
            if latest_chapter and latest_chapter > last_chapter:
                for chapter in range(last_chapter + 1, latest_chapter + 1):
                    url = manga["url"].format(chapter=chapter)
                    if notify_on_new:
                        notify(f"New chapter available for {name}: Chapter {chapter}\n{url}")
                    logger.info("chapter_found name=%s chapter=%s", name, chapter)
                state_entry["last_chapter"] = latest_chapter
            logger.info("series_check_finished name=%s latest_known_chapter=%s", name, state_entry["last_chapter"])
            save_state(state)
            continue

        while True:
            url = manga["url"].format(chapter=next_chapter)
            logger.info("chapter_check_started name=%s chapter=%s url=%s", name, next_chapter, url)
            if not check_chapter(manga, next_chapter, strategy):
                break

            if notify_on_new:
                notify(f"New chapter available for {name}: Chapter {next_chapter}\n{url}")

            state_entry["last_chapter"] = next_chapter
            logger.info("chapter_found name=%s chapter=%s", name, next_chapter)
            next_chapter += 1
            time.sleep(1)

        logger.info("series_check_finished name=%s latest_known_chapter=%s", name, state_entry["last_chapter"])
        save_state(state)
    logger.info("checker_finished series_count=%s", len(subscription))


def run_probe_mode(name: str, url: str, known_chapter: int) -> int:
    logger.info("probe_started name=%s known_chapter=%s", name, known_chapter)
    strategy, results = run_probe(url, known_chapter)
    logger.info("probe_result name=%s strategy=%s", name, strategy)
    logger.debug("probe_results=%s", results)
    if strategy["method"] in {"unknown", "unreachable"}:
        logger.error("probe_failed name=%s strategy=%s", name, strategy["method"])
        return 1

    state = load_state()
    state[name] = {
        "last_chapter": known_chapter,
        "strategy": strategy,
    }
    save_state(state)
    logger.info("probe_saved name=%s strategy=%s", name, strategy["method"])
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["check", "probe"], default="check")
    parser.add_argument("--name")
    parser.add_argument("--url")
    parser.add_argument("--known-chapter", type=int)
    args = parser.parse_args()

    if args.mode == "probe":
        if not args.name or not args.url or not args.known_chapter:
            parser.error("--mode probe requires --name, --url, and --known-chapter")
        return run_probe_mode(args.name, args.url, args.known_chapter)

    run_check()
    return 0

if __name__ == "__main__":
    try:
        from src.logging_config import configure_logging
    except ModuleNotFoundError:
        from logging_config import configure_logging

    configure_logging()
    raise SystemExit(main())
