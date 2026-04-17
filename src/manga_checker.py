import json
import httpx
import yaml
import os
from dotenv import load_dotenv
from pathlib import Path
import logging
import time

load_dotenv()

# -- Configuration --
STATE_FILE = Path(__file__).parent / "state.json"
SUBSCRIPTION_FILE = Path(__file__).parent.parent / "config" / "subscription.yaml"
TG_TOKEN = os.getenv("TG_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

logger = logging.getLogger(__name__)

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE, "r") as f:
            raw_state = json.load(f)
            logger.info("state_loaded path=%s entries=%s", STATE_FILE, len(raw_state))
            return {name: int(chapter) for name, chapter in raw_state.items()}

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

def check_chapter(url) -> bool:
    try:
        response = httpx.head(
            url,
            follow_redirects=True,
            timeout=10,
            headers=REQUEST_HEADERS,
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
                headers=REQUEST_HEADERS,
            )
            logger.debug(
                "chapter_checked method=GET url=%s status_code=%s",
                url,
                fallback.status_code,
            )
            return fallback.status_code == 200

        return False
    except httpx.RequestError as exc:
        logger.error("chapter_check_failed url=%s error=%s", url, exc)
        return False

def notify(message: str) -> None:
    if not TG_TOKEN or not TG_CHAT_ID:
        logger.warning("notify_skipped reason=missing_telegram_env")
        return

    httpx.post(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        data={"chat_id": TG_CHAT_ID, "text": message},
    )
    logger.info("notification_sent channel=telegram")


def main():
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
        url_template = manga["url"]
        notify_on_new = manga.get("notify", False)
        last_chapter = state.get(name, 0)
        next_chapter = last_chapter + 1

        logger.info("series_check_started name=%s next_chapter=%s", name, next_chapter)

        while True:
            url = url_template.format(chapter=next_chapter)
            logger.info("chapter_check_started name=%s chapter=%s url=%s", name, next_chapter, url)
            if not check_chapter(url):
                break
            
            if notify_on_new:
                notify(f"New chapter available for {name}: Chapter {next_chapter}\n{url}")
                
            state[name] = next_chapter
            logger.info("chapter_found name=%s chapter=%s", name, next_chapter)
            next_chapter += 1

            time.sleep(1)

        logger.info("series_check_finished name=%s latest_known_chapter=%s", name, state.get(name, last_chapter))
        save_state(state)
    logger.info("checker_finished series_count=%s", len(subscription))

if __name__ == "__main__":
    try:
        from src.logging_config import configure_logging
    except ModuleNotFoundError:
        from logging_config import configure_logging

    configure_logging()
    main()
