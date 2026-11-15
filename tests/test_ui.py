import pytest

from dome.case import Case
from dome.supervisor import run_scripted
from dome.ui import app as ui


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "CASES", tmp_path)
    monkeypatch.setattr(ui, "RECORDED", tmp_path / "recorded")
    case = Case.open("ui-a", scenario="ring_a", root=tmp_path, reset=True)
    run_scripted(case)
    return ui.app.test_client()


def test_serves_case_files_from_a_scripted_run(client):
    r = client.get("/case/ui-a/file/rings.json")
    assert r.status_code == 200 and r.get_json()["rings"]
    brief = client.get("/case/ui-a/file/brief.json").get_json()
    assert brief["leads"][0]["tier"] == "High"
    assert all("address" not in lead for lead in brief["leads"])          # never sent
    cands = client.get("/case/ui-a/file/candidates.json").get_json()
    assert all("address" not in c for z in cands["zones"] for c in z["candidates"])


@pytest.mark.parametrize("path", [
    "/case/ui-a/file/../../.env", "/case/ui-a/file/..%2F..%2F.env", "/case/ui-a/file/log.jsonl",
    "/case/ui-a/file/input.json", "/case/..%2F..%2Fdome/file/brief.json", "/case/nope/file/brief.json"])
def test_refuses_anything_off_the_whitelist(client, path):
    assert client.get(path).status_code == 404


def test_log_is_incremental(client):
    first = client.get("/case/ui-a/log?since=0").get_json()
    assert first["rows"] and first["next"] == len(first["rows"])
    assert client.get(f"/case/ui-a/log?since={first['next']}").get_json()["rows"] == []


def test_page_and_summary_have_no_banned_words(client):
    page = client.get("/").get_data(as_text=True).lower()
    summary = client.get("/case/ui-a/summary").get_data(as_text=True).lower()
    for text in (page, summary):
        for word in ("wallet", " dm ", "collector", "handler"):
            assert word not in text
    assert "synthetic" in page
