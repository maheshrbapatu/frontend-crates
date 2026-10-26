# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import hashlib
import json
from pathlib import Path

import pytest

from capture_execution import execution_outcome, validate_adapter_bundle, validate_events, validate_execution
from capture_stimulus import batch_final_events
from unified_history import load_yaml


@pytest.mark.parametrize("expected,actual", [(True, 1), (1, True), (0.0, -0.0), (-0.0, 0.0)])
def test_rehashed_capture_cannot_change_request_value_types(expected, actual):
    job = {"cases": [{"id": "case", "request": {"tools": [{"value": expected}]}}]}
    job_bytes = json.dumps(job).encode()
    results = {"case": {"capture_input": {"tools": [{"value": actual}]}, "chunks": []}}
    document = {"vllm_version": "1.0.0", "results": results, "provenance": {
        "implementation": "vllm_python", "version": "1.0.0",
        "source_sha256": "a" * 64, "adapter_sha256": "b" * 64,
        "job_sha256": hashlib.sha256(job_bytes).hexdigest(),
        "results_sha256": hashlib.sha256(json.dumps(results, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
    }}
    with pytest.raises(ValueError, match="request mismatch"):
        validate_execution(document, job, job_bytes, "vllm_python", "1.0.0")


@pytest.mark.parametrize("corruption", [None, "empty", "traversal", "symlink", "bytes", "support"])
def test_adapter_bundle_validates_ordered_bytes_and_support(tmp_path, corruption):
    (tmp_path / "probe").write_bytes(b"probe")
    (tmp_path / "helper").write_bytes(b"helper")
    manifest = {"files": [{"path": "probe", "sha256": hashlib.sha256(b"probe").hexdigest()}],
                "support_files": [{"path": "helper", "sha256": hashlib.sha256(b"helper").hexdigest()}]}
    if corruption == "empty":
        manifest["files"] = []
    elif corruption == "traversal":
        manifest["files"][0]["path"] = "../probe"
    elif corruption == "symlink":
        (tmp_path / "probe").unlink()
        (tmp_path / "probe").symlink_to(tmp_path / "helper")
    elif corruption == "bytes":
        (tmp_path / "probe").write_bytes(b"altered")
    elif corruption == "support":
        (tmp_path / "helper").write_bytes(b"altered")
    if corruption:
        with pytest.raises(ValueError, match="adapter"):
            validate_adapter_bundle(tmp_path, manifest)
    else:
        assert validate_adapter_bundle(tmp_path, manifest) == hashlib.sha256(b"probe").hexdigest()


def test_committed_muse_spark_stream_phase_events_are_executed():
    capture = Path(__file__).resolve().parents[2] / "fixtures-unified-v2/families/muse_spark/dynamo_v2.yaml"
    document = load_yaml(capture)
    phase_records = [row["value"]["observation"]["value"] for row in document["records"].values()
                     if "value" in row["value"]["observation"]
                     and any(event["kind"] == "message_start" for event in row["value"]["observation"]["value"].get("assembled", []))]
    assert phase_records
    assert {event["phase"] for record in phase_records for event in record["assembled"] if event["kind"] == "message_start"} == {"commentary", "final_answer"}
    for record in phase_records:
        assert execution_outcome(record, "stream") == ("executed", None)


@pytest.mark.parametrize("phase", ["commentary", "final_answer"])
@pytest.mark.parametrize("chunk_shape", ["list", "expected"])
@pytest.mark.parametrize("failed", [False, True])
def test_phase_events_validate_in_success_and_partial_streams(phase, chunk_shape, failed):
    events = [{"kind": "message_start", "phase": phase}, {"kind": "text", "text": "answer"}, {"kind": "message_end"}]
    chunks = [events if chunk_shape == "list" else {"expected": events}]
    record = {"assembled": events, "chunks": chunks}
    if failed:
        record.update(error="interrupted", partial_chunks=chunks)
    assert execution_outcome(record, "stream") == (("parser_error", None) if failed else ("executed", None))


@pytest.mark.parametrize("event", [
    {"kind": "message_start"},
    *({"kind": "message_start", "phase": phase} for phase in (None, True, 1, [], {}, "analysis", "", "Commentary")),
])
def test_message_start_rejects_missing_or_invalid_phase(event):
    with pytest.raises(ValueError, match="valid phase"):
        validate_events([event])


def test_phase_support_preserves_batch_final_projection_and_unknown_kind_rejection():
    final = {"reasoning_text": "reason", "normal_text": "answer", "calls": []}
    events = batch_final_events(final)
    assert execution_outcome({"batch_final": final, "assembled": events}, "batch") == ("executed", None)
    with pytest.raises(ValueError, match="differs from final fields"):
        execution_outcome({"batch_final": final, "assembled": [{"kind": "message_start", "phase": "final_answer"}, *events]}, "batch")
    with pytest.raises(ValueError, match="invalid kind"):
        validate_events([{"kind": "unknown"}])
