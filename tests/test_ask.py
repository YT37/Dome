import json

from dome import ask


class Stub:
    """A stand-in chat model that returns a fixed reply (no network)."""

    def __init__(self, reply: dict):
        self.reply, self.seen = json.dumps(reply), None

    def invoke(self, messages):
        self.seen = messages
        return type("Msg", (), {"content": self.reply})()


def make_case(tmp_path):
    d = tmp_path / "real-a"
    d.mkdir()
    (d / "brief.json").write_text(json.dumps({"leads": [{"display_name": "Building A (synthetic case)", "tier": "High",
                                                          "reasons": ["P 0.68: 13 of 19 room photos match the unit scan"]}]}))
    (d / "rings.json").write_text(json.dumps({"rings": [{"ring_id": "R-1", "members": ["acct_103", "acct_118"]}]}))
    return tmp_path


def test_answers_with_citations_that_exist(tmp_path):
    root = make_case(tmp_path)
    stub = Stub({"answer": "Building A is High because its room photos match the scan (P 0.68).",
                 "citations": [{"file": "case/real-a/brief.json", "path": "leads[0].reasons[0]"}], "answerable": True})
    out = ask.answer("real-a", "Why is Building A High?", root=root, model=stub)
    assert out["answerable"] and out["citations"] == [{"file": "case/real-a/brief.json", "path": "leads[0].reasons[0]"}]
    prompt = str(stub.seen)
    assert "case/real-a/brief.json" in prompt and "answer_key" not in prompt


def test_refuses_out_of_case_question(tmp_path):
    root = make_case(tmp_path)
    stub = Stub({"answer": "Not in the files.", "citations": [], "answerable": False})
    out = ask.answer("real-a", "What is the suspect's home address?", root=root, model=stub)
    assert out == {"answer": ask.NOT_IN_CASE, "citations": [], "answerable": False}


def test_drops_citations_outside_the_case_or_to_missing_fields(tmp_path):
    root = make_case(tmp_path)
    stub = Stub({"answer": "Made up.", "answerable": True, "citations": [
        {"file": "data/answer_key/answer_key.json", "path": "A.members"},
        {"file": "case/real-a/brief.json", "path": "leads[5].reasons[0]"},
        {"file": "case/other/brief.json", "path": "leads[0]"}]})
    out = ask.answer("real-a", "Who is in the ring?", root=root, model=stub)
    assert out["answerable"] is False and out["answer"] == ask.NOT_IN_CASE


def test_bad_case_id_reads_nothing(tmp_path):
    assert ask.case_files("../../data/answer_key", root=tmp_path) == {}
    assert ask.answer("../x", "anything", root=tmp_path, model=Stub({}))["answerable"] is False
