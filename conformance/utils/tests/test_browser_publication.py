# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Browser workers share immutable publications, with separate latest/history owners."""
import gzip
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import conftest
import pytest


@pytest.mark.parametrize("restored_mode", ["latest", "history"])
def test_history_reuses_only_a_restored_history_publication(tmp_path, monkeypatch, restored_mode):
    restored = tmp_path / "restored"
    catalog = restored / "conformance/viewer-resolved-catalog.json.gz"
    catalog.parent.mkdir(parents=True)
    catalog.write_bytes(gzip.compress(json.dumps({"capture_generation": {"mode": restored_mode}}).encode()))
    monkeypatch.setenv("CONFORMANCE_PUBLISHED_SITE", str(restored))
    monkeypatch.delenv("CONFORMANCE_HISTORY_SITE", raising=False)
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    monkeypatch.setattr(conftest.capture_sources, "publication_inputs_digest", lambda *args, **kwargs: "history")
    calls = []

    def publish(root, destination, *, extra):
        calls.append(extra)
        destination.mkdir()
        (destination / "index.html").write_text("published")
        (destination / "conformance").mkdir()
        (destination / "conformance/viewer-publication.json").write_text(json.dumps({"publisher_inputs_sha256": "history"}))

    monkeypatch.setattr(conftest, "publish", publish)
    site = conftest._browser_publication(SimpleNamespace(getbasetemp=lambda: tmp_path / "fresh"), tmp_path / "history")
    assert (site == restored) == (restored_mode == "history")
    assert calls == ([] if restored_mode == "history" else [("--include-history", "--history-source", str(tmp_path / "history"))])


def test_workers_publish_each_mode_once(tmp_path, monkeypatch):
    monkeypatch.delenv('CONFORMANCE_PUBLISHED_SITE', raising=False)
    monkeypatch.delenv('CONFORMANCE_HISTORY_SITE', raising=False)
    monkeypatch.setenv('PYTEST_XDIST_WORKER', 'gw-test')
    barrier = threading.Barrier(8)
    calls = []

    def identity(root, *, include_history, history_source):
        barrier.wait(timeout=10)
        return 'history' if include_history else 'latest'

    def publish(root, destination, *, extra):
        mode = 'history' if extra else 'latest'
        calls.append(mode)
        envelope = destination / 'conformance/viewer-publication.json'
        envelope.parent.mkdir(parents=True)
        (destination / 'index.html').write_text('published')
        envelope.write_text(json.dumps({'publisher_inputs_sha256': mode}))

    monkeypatch.setattr(conftest.capture_sources, 'publication_inputs_digest', identity)
    monkeypatch.setattr(conftest, 'publish', publish)

    def worker(index):
        base = tmp_path / f'gw{index}'
        factory = SimpleNamespace(getbasetemp=lambda: base)
        history = tmp_path / 'history' if index % 2 else None
        return conftest._browser_publication(factory, history)

    with ThreadPoolExecutor(max_workers=8) as pool:
        sites = list(pool.map(worker, range(8)))
    assert sorted(calls) == ['history', 'latest']
    assert len(set(sites[::2])) == len(set(sites[1::2])) == 1
    assert sites[0] != sites[1]
