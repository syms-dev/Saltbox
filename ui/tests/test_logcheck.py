"""Recurring errors in container logs, and the ones that come with an explanation."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from saltbox_ui import logcheck
from saltbox_ui.daemon import Services, create_app
from saltbox_ui.daemon import routes as daemon_routes
from saltbox_ui.layout import Layout

T = "2026-11-13T14:46:35.123456789Z "
AUTOSCAN = (
    T
    + "Nov 13 14:46:35 ERR Anchor files unavailable, retaining queued scans "
    + 'missing_anchors=["/mnt/unionfs/mounted.bin"]'
)
BAZARR = (
    "2026-11-13T07:06:22.300000000Z 2026-11-13 07:06:22,275 - root                             "
    "(7d2c7209db30) :  ERROR (utils:55) - BAZARR Error ('.iso' is not a valid video extension) "
    "trying to get video information for this file: "
    "/mnt/unionfs/Media/Movies/American History X (1998)/American History X (1998).iso"
)


def test_error_lines_are_told_from_ordinary_ones() -> None:
    for line in (
        "Nov 13 14:46:35 ERR Anchor files unavailable",
        "2026-11-13 07:06:22,275 - root :  ERROR (utils:55) - BAZARR Error",
        "[Error] DownloadedEpisodesImportService: Import failed",
        'time="2026-11-13" level=error msg="dial tcp: connection refused"',
        '{"level":"error","msg":"boom"}',
        "panic: runtime error: index out of range",
        "Traceback (most recent call last):",
        "CRITICAL: cannot continue",
    ):
        assert logcheck.is_error(line), line
    for line in (
        "[Info] RssSyncService: RSS Sync Completed",
        "INF Scan moved to target",
        "0 errors, 12 files checked",
        "GET /api/v3/error-pages 200",
        "level=info msg=started",
    ):
        assert not logcheck.is_error(line), line


def test_signature_ignores_what_changes_between_occurrences() -> None:
    first = logcheck.signature(
        "[Error] Import failed for /downloads/Show.S01E02/file.mkv after 3 tries (id 9f8e7d6c5b4a)"
    )
    second = logcheck.signature(
        "[Error] Import failed for /downloads/Other.S09E11/x.mkv after 12 tries (id 0a1b2c3d4e5f)"
    )
    assert first == second == "[Error] Import failed for <path> after # tries (id <id>)"
    assert logcheck.clean("\x1b[31mNov 13 14:46:35 ERR boom\x1b[0m") == "ERR boom"
    assert logcheck.clean("2026-11-13 07:06:22,275 - root : ERROR x") == "root : ERROR x"
    assert logcheck.split_time(T + "hello") == ("2026-11-13T14:46:35Z", "hello")


def test_known_errors_come_with_what_they_mean_and_what_to_do() -> None:
    found = logcheck.analyse("autoscan", [AUTOSCAN] * 40 + [T + "INF Scan moved to target"])
    assert len(found) == 1
    group = found[0]
    assert group["count"] == 40 and group["last_seen"] == "2026-11-13T14:46:35Z"
    assert group["message"].startswith("ERR Anchor files unavailable")
    assert group["rule"]["id"] == "autoscan-anchor" and group["rule"]["severity"] == "problem"
    assert "touch /mnt/local/mounted.bin" in " ".join(group["rule"]["fix"])

    # Seen once is enough for a known one; each file is a different line but one finding.
    other = BAZARR.replace("American History X (1998)", "Another Film (2001)")
    bazarr = logcheck.analyse("bazarr", [BAZARR, other])
    assert [(g["rule"]["id"], g["count"]) for g in bazarr] == [("bazarr-not-a-video", 2)]
    assert bazarr[0]["rule"]["severity"] == "notice"
    assert "Another Film (2001)" in bazarr[0]["message"]  # the latest occurrence is shown

    # A rule for one app does not fire on another app's log.
    assert logcheck.analyse("sonarr", [AUTOSCAN]) == []


def test_unknown_errors_are_listed_only_when_they_recur() -> None:
    def failed(n: int) -> str:
        return f"{T}[Error] ImportService: Import failed for /downloads/file{n}.mkv"

    once = logcheck.analyse("sonarr", [failed(1), T + "[Info] fine"])
    assert once == []
    lines = [failed(n) for n in range(5)] + [T + "[Error] Something else"]
    lines += [T + "[Error] No space left on device"]
    found = logcheck.analyse("sonarr", lines)
    assert [(g["rule"] and g["rule"]["id"], g["count"]) for g in found] == [
        ("disk-full", 1),  # known ones first
        (None, 5),
    ]
    assert found[1]["message"] == "[Error] ImportService: Import failed for /downloads/file4.mkv"
    # General rules need an error line: a note about permissions at info level is not one.
    assert logcheck.analyse("sonarr", [T + "[Info] Permission denied is handled"]) == []


def container(name: str, managed: bool = True) -> dict:
    return {
        "name": name,
        "status": "running",
        "health": None,
        "managed": managed,
        "image_ref": f"example/{name}",
        "network_mode": "saltbox",
        "urls": [],
        "labels": {},
    }


def test_problems_route_scans_saltbox_containers_and_caches(
    scratch_layout: Layout, fake_sb: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        daemon_routes,
        "_containers_or_none",
        lambda: [container("autoscan"), container("sonarr"), container("stray", managed=False)],
    )
    calls: list[str] = []

    def docker(args: list[str]) -> tuple[int, str]:
        assert args[:6] == ["docker", "logs", "--since", "24h", "--tail", "3000"]
        calls.append(args[-1])
        if args[-1] == "autoscan":
            return 0, "\n".join([AUTOSCAN] * 3)
        return 0, T + "[Info] all good\n"

    services = Services(scratch_layout, log_runner=docker)
    client = TestClient(create_app(services=services))
    data = client.get("/api/problems").json()
    assert sorted(calls) == ["autoscan", "sonarr"]  # not the container Saltbox does not manage
    assert data["available"] is True and data["scanned"] == 2 and data["window"] == "24h"
    assert [c["name"] for c in data["containers"]] == ["autoscan"]
    assert data["containers"][0]["app"] == {
        "repo": "saltbox",
        "role": "autoscan",
        "title": "Autoscan",
    }
    assert data["containers"][0]["groups"][0]["rule"]["id"] == "autoscan-anchor"
    client.get("/api/problems")
    assert len(calls) == 2  # kept for ten minutes
    client.get("/api/problems?refresh=true")
    assert len(calls) == 4
