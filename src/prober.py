from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx
from curl_cffi import requests as cffi_requests


PROBE_TESTS = [
    ("known_good", "baseline"),
    ("next_chapter", "sanity check"),
    ("extreme_high", "definitely missing"),
]

KEYWORDS = ["404", "not found", "not available", "does not exist"]
CHAPTER_RE = re.compile(r"chapter-(\d+)")


def derive_referer(url_template: str) -> str:
    parsed = urlparse(url_template.format(chapter=1))
    return f"{parsed.scheme}://{parsed.netloc}/"


def head_or_get(url: str) -> dict:
    response = httpx.head(url, follow_redirects=True, timeout=10)
    if response.status_code in {403, 405}:
        response = httpx.get(url, follow_redirects=True, timeout=10)
        method = "GET"
    else:
        method = "HEAD"

    return {
        "method": method,
        "status_code": response.status_code,
        "final_url": str(response.url),
    }


def cffi_get(url: str, referer: str) -> dict:
    response = cffi_requests.get(
        url,
        impersonate="chrome136",
        allow_redirects=True,
        timeout=20,
        headers={"referer": referer},
    )
    text_head = response.text[:5000]
    return {
        "status_code": response.status_code,
        "final_url": str(response.url),
        "text_head": text_head,
        "text_lower": response.text.lower(),
        "content_length": len(response.text),
    }


def run_probe(url_template: str, known_chapter: int) -> tuple[dict, dict]:
    referer = derive_referer(url_template)
    chapter_values = {
        "known_good": known_chapter,
        "next_chapter": known_chapter + 1,
        "extreme_high": 99999,
    }
    results: dict[str, dict] = {}

    for label, _purpose in PROBE_TESTS:
        chapter = chapter_values[label]
        url = url_template.format(chapter=chapter)
        item: dict = {"chapter": chapter, "url": url}
        try:
            item["standard"] = head_or_get(url)
        except httpx.RequestError as exc:
            item["standard_error"] = str(exc)
        try:
            item["cffi"] = cffi_get(url, referer)
        except cffi_requests.RequestsError as exc:
            item["cffi_error"] = str(exc)
        results[label] = item

    strategy = analyze_probe_results(results, known_chapter, referer)
    return strategy, results


def analyze_probe_results(results: dict, known_chapter: int, referer: str) -> dict:
    known = results["known_good"]
    fake = results["extreme_high"]
    next_result = results["next_chapter"]

    known_std = known.get("standard")
    fake_std = fake.get("standard")
    if known_std and fake_std:
        if known_std["status_code"] == 200 and fake_std["status_code"] == 404:
            return {"method": "status_code", "use_cffi": False}
        if (
            known_std["status_code"] == 200
            and fake_std["final_url"] != fake["url"]
            and fake_std["final_url"] != known_std["final_url"]
        ):
            return {
                "method": "redirect",
                "use_cffi": False,
                "redirect_target": fake_std["final_url"],
            }

    known_cffi = known.get("cffi")
    fake_cffi = fake.get("cffi")
    next_cffi = next_result.get("cffi")
    if not known_cffi or not fake_cffi:
        return {"method": "unknown", "use_cffi": True, "referer": referer}

    redirected_match = CHAPTER_RE.search(known_cffi["final_url"])
    if (
        known_cffi["status_code"] == 200
        and fake_cffi["status_code"] == 200
        and known_cffi["final_url"] == fake_cffi["final_url"]
        and known_cffi["final_url"] != known["url"]
        and redirected_match
    ):
        redirected_chapter = int(redirected_match.group(1))
        if redirected_chapter != known_chapter:
            return {
                "method": "redirect_latest",
                "use_cffi": True,
                "referer": referer,
            }

    known_has_title = f"Chapter {known_chapter}" in known_cffi["text_head"]
    fake_has_title = f"Chapter 99999" in fake_cffi["text_head"]
    next_has_title = next_cffi and f"Chapter {known_chapter + 1}" in next_cffi["text_head"]
    if known_cffi["status_code"] == 200 and known_has_title and not fake_has_title:
        strategy = {"method": "title_match", "use_cffi": True, "referer": referer}
        if next_has_title:
            strategy["next_chapter_hint"] = "present"
        return strategy

    fake_keywords = [kw for kw in KEYWORDS if kw in fake_cffi["text_lower"]]
    known_keywords = [kw for kw in KEYWORDS if kw in known_cffi["text_lower"]]
    if fake_keywords and not known_keywords:
        return {
            "method": "keyword",
            "use_cffi": True,
            "referer": referer,
            "keywords": fake_keywords,
        }

    known_len = known_cffi["content_length"]
    fake_len = fake_cffi["content_length"]
    ratio = fake_len / max(known_len, 1)
    if ratio > 2.0 or ratio < 0.3:
        return {
            "method": "content_length",
            "use_cffi": True,
            "referer": referer,
            "expected_length_range": [int(known_len * 0.5), int(known_len * 1.5)],
        }

    return {"method": "unknown", "use_cffi": True, "referer": referer}
