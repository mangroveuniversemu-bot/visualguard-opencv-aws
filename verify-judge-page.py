"""Fail closed when the public judge page drifts from the current AWS boundary."""

from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path


LIVE_URL = "https://zkdmdpnivndaqlsxgm4umbjwjy0akezq.lambda-url.us-east-1.on.aws/"
STALE_CLAIM = "a public AWS inference endpoint is not available here"
REQUIRED_TEXT = (
    "The static replay below never calls AWS.",
    "Shared daily limit: five inspections, resets at midnight Asia/Taipei.",
    "Synthetic inputs only. Real-camera accuracy and physical control remain unverified.",
    "This static page reads saved evidence and makes no AWS requests.",
    "inference requires an explicit click and consumes one shared daily slot.",
)


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[dict[str, str]] = []
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self.links.append({key: value or "" for key, value in attrs})

    def handle_data(self, data: str) -> None:
        self.text.append(data)


def verify(source: str) -> dict[str, int | str]:
    parser = PageParser()
    parser.feed(source)
    visible_text = " ".join(" ".join(parser.text).split())
    live_links = [link for link in parser.links if link.get("href") == LIVE_URL]

    if STALE_CLAIM in visible_text:
        raise ValueError("STALE_PUBLIC_ENDPOINT_CLAIM")
    if len(live_links) < 2:
        raise ValueError("LIVE_AWS_JUDGE_PATH_MISSING")
    if any(link.get("target") != "_blank" for link in live_links):
        raise ValueError("LIVE_AWS_LINK_TARGET_UNSAFE")
    if any(not {"noopener", "noreferrer"}.issubset(set(link.get("rel", "").split())) for link in live_links):
        raise ValueError("LIVE_AWS_LINK_REL_UNSAFE")
    for phrase in REQUIRED_TEXT:
        if phrase not in visible_text:
            raise ValueError(f"CLAIM_BOUNDARY_MISSING:{phrase}")

    return {
        "result": "PASS",
        "live_aws_links": len(live_links),
        "required_claims": len(REQUIRED_TEXT),
    }


def negative_controls(source: str) -> dict[str, str]:
    controls = {
        "stale_endpoint_claim": source.replace(
            "The separate live AWS inspector is linked above and requires an explicit inspection action.",
            STALE_CLAIM,
        ),
        "missing_live_url": source.replace(LIVE_URL, "#removed"),
        "missing_quota_boundary": source.replace(REQUIRED_TEXT[1], "Quota unavailable."),
        "missing_field_boundary": source.replace(REQUIRED_TEXT[2], "Synthetic inputs only."),
        "missing_static_boundary": source.replace(REQUIRED_TEXT[3], "Saved evidence."),
        "unsafe_external_link": source.replace('rel="noopener noreferrer"', 'rel="noreferrer"'),
    }
    results: dict[str, str] = {}
    for name, mutated in controls.items():
        try:
            verify(mutated)
        except ValueError as error:
            results[name] = str(error)
        else:
            raise AssertionError(f"negative control accepted: {name}")
    return results


if __name__ == "__main__":
    html = Path(__file__).with_name("index.html").read_text(encoding="utf-8")
    report = verify(html)
    controls = negative_controls(html)
    report["negative_controls"] = len(controls)
    report["negative_control_results"] = controls
    print(json.dumps(report, sort_keys=True))
