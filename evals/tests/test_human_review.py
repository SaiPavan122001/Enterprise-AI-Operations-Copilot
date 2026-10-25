"""Human review workflow: blind export, validation, merge and v1.1 build never
invent human input and never modify v1. Uses temporary files only."""

import csv
import json

import pytest

from evals import claim_calibration, human_review as hr


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


@pytest.fixture
def files(tmp_path, monkeypatch):
    claims = tmp_path / "claims.csv"
    write_csv(claims, [{"claim_id": "q1#1", "question": "q", "claim": "c", "evidence": "e", "judge_verdict": "supported",
                        "assistant_label": "supported", "human_label": "", "human_note": ""}])
    samples = tmp_path / "samples.csv"
    write_csv(samples, [{"sample_id": "1", "metric": "faithfulness", "question": "q", "reference_answer": "r",
                         "retrieved_contexts": "x", "answer_evaluated": "a", "judge_score": "0.9", "judge_pass": "1",
                         "human_label": "", "human_notes": ""}])
    corr = tmp_path / "corr.json"
    corr.write_text(json.dumps({"corrections": [
        {"id": "q1", "question": "q", "question_type": "single_chunk", "old_reference": "old1",
         "proposed_reference": "new1", "evidence": ["e"]},
        {"id": "q2", "question": "q", "question_type": "single_chunk", "old_reference": "old2",
         "proposed_reference": "new2", "evidence": ["e"]}]}), encoding="utf-8")
    v1 = tmp_path / "v1.jsonl"
    v1.write_text("".join(json.dumps({"id": i, "question": "q", "reference_answer": f"old{i[-1]}"}) + "\n"
                          for i in ("q1", "q2", "q3")), encoding="utf-8")
    review = tmp_path / "review"
    for name, value in {"CLAIMS": claims, "SAMPLES": samples, "CORRECTIONS": corr, "V1": v1,
                        "V11": tmp_path / "v11.jsonl", "REVIEW_DIR": review,
                        "CLAIMS_BLIND": review / "claims_blind.csv", "SAMPLES_BLIND": review / "samples_blind.csv",
                        "REFS_REVIEW": review / "refs.csv", "AUDIT_LOG": review / "AUDIT_LOG.jsonl"}.items():
        monkeypatch.setattr(hr, name, str(value))
    hr.export()
    return tmp_path


def fill(path, **values):
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    for k, v in values.items():
        key, col = k.split("__")
        for r in rows:
            if key in r.values():
                r[col] = v
    write_csv(path, rows)


def test_blind_export_hides_judge_and_ai_labels(files):
    header = open(hr.CLAIMS_BLIND, encoding="utf-8").readline()
    assert "judge" not in header and "assistant" not in header
    assert all(not r["human_label"] for r in csv.DictReader(open(hr.CLAIMS_BLIND, encoding="utf-8")))


def test_export_never_overwrites_reviewer_input(files):
    fill(hr.CLAIMS_BLIND, **{"q1#1__human_label": "supported"})
    with pytest.raises(SystemExit):
        hr.export()


def test_invalid_labels_and_decisions_reported(files):
    fill(hr.CLAIMS_BLIND, **{"q1#1__human_label": "probably"})
    fill(hr.REFS_REVIEW, **{"q1__decision": "approve"})          # no reviewer
    problems = hr.validate(quiet=True)["problems"]
    assert len(problems) == 2


def test_merge_copies_only_human_labels(files):
    fill(hr.CLAIMS_BLIND, **{"q1#1__human_label": "unsupported"})
    hr.merge()
    rows = list(csv.DictReader(open(hr.CLAIMS, encoding="utf-8")))
    assert rows[0]["human_label"] == "unsupported" and rows[0]["assistant_label"] == "supported"
    samples = list(csv.DictReader(open(hr.SAMPLES, encoding="utf-8")))
    assert samples[0]["human_label"] == ""                       # unlabelled stays empty


def test_agreement_refuses_without_human_labels(files):
    with pytest.raises(SystemExit):
        claim_calibration.agreement(hr.CLAIMS, "human")


def test_v11_only_from_approved_corrections_and_v1_untouched(files):
    before = open(hr.V1, encoding="utf-8").read()
    fill(hr.REFS_REVIEW, **{"q1__decision": "approve", "q1__reviewer": "sme"})
    fill(hr.REFS_REVIEW, **{"q2__decision": "reject", "q2__reviewer": "sme"})
    hr.build_v11()
    items = {json.loads(line)["id"]: json.loads(line) for line in open(hr.V11, encoding="utf-8")}
    assert items["q1"]["reference_answer"] == "new1" and items["q1"]["reference_review"]["reviewer"] == "sme"
    assert items["q2"]["reference_answer"] == "old2"             # rejected -> v1 reference kept
    assert open(hr.V1, encoding="utf-8").read() == before
    with pytest.raises(SystemExit):
        hr.build_v11()                                           # built once


def test_v11_not_built_without_approvals(files):
    with pytest.raises(SystemExit):
        hr.build_v11()


def test_merge_archives_original_and_writes_audit_log(files):
    before = open(hr.CLAIMS, encoding="utf-8").read()
    fill(hr.CLAIMS_BLIND, **{"q1#1__human_label": "supported"})
    hr.merge()
    archived = [p for p in files.iterdir() if p.name.startswith("claims.pre-merge-")]
    assert len(archived) == 1 and archived[0].read_text(encoding="utf-8") == before
    log = [json.loads(line) for line in open(hr.AUDIT_LOG, encoding="utf-8")]
    assert log[-1]["action"] == "merge_human_labels" and log[-1]["labels"] == 1


def test_merge_with_no_labels_changes_nothing(files):
    before = open(hr.CLAIMS, encoding="utf-8").read()
    hr.merge()
    assert open(hr.CLAIMS, encoding="utf-8").read() == before
    assert not [p for p in files.iterdir() if ".pre-merge-" in p.name]


def test_v11_build_is_audited_with_reviewers(files):
    fill(hr.REFS_REVIEW, **{"q1__decision": "approve", "q1__reviewer": "sme"})
    hr.build_v11()
    log = [json.loads(line) for line in open(hr.AUDIT_LOG, encoding="utf-8")]
    assert log[-1]["action"] == "build_testset_v1.1"
    assert log[-1]["approved"] == [{"id": "q1", "decision": "approve", "reviewer": "sme"}]
