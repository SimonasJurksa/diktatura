"""Y1–Y7: užpildų valymas (diktatura.fillers), transkripcijų skaitymas (diktatura.transcripts) ir MCP serveris
(diktatura.mcp_server per bin/mcp-server.sh — tikras stdio JSON-RPC)."""
import json
import subprocess
from datetime import date, datetime, timedelta

import pytest

from testenv import REPO


# ── Y1: užpildai ──

@pytest.mark.parametrize("raw, words, want", [
    ("Ee, aš manau, kad gerai.", "", "Aš manau, kad gerai."),
    ("Mhm.", "", ""),
    ("aš aš aš manau", "", "aš manau"),
    ("aš manau aš manau, kad taip", "", "aš manau, kad taip"),
    ("labas, ee, kaip sekasi?", "", "labas, kaip sekasi?"),
    ("Aaa, supratau", "", "Supratau"),
    ("Taip, taip, taip.", "", "Taip."),
    ("emm... gerai", "", "gerai"),
    ("Parašyk e. paštu.", "", "Parašyk e. paštu."),             # „e." — santrumpa, ne užpildas
    ("E-paštas veikia", "", "E-paštas veikia"),
    ("Nu, tipo, reikia daryti.", "nu,tipo", "Reikia daryti."),
    ("Nu, tipo, reikia daryti.", "", "Nu, tipo, reikia daryti."),  # be vartotojo žodžių — lieka
    ("Mama sakė nu ir gerai", "nu", "Mama sakė ir gerai"),
    ("numatyta tipologija", "nu,tipo", "numatyta tipologija"),    # tik atskiri žodžiai
])
def test_y1_clean(raw, words, want):
    from diktatura import fillers
    assert fillers.clean(raw, words) == want


def test_y1_parse_words():
    from diktatura import fillers
    assert fillers.parse_words(" Nu, tipo ,,žinai ") == ("nu", "tipo", "žinai") and fillers.parse_words("") == ()


def test_y2_words_setting_kind(env):
    from diktatura import config
    assert config.coerce("FILLER_WORDS", " Nu , Tipo ") == "nu,tipo" and config.coerce("FILLER_WORDS", "") == ""
    for bad in ("labas rytas", "nu;tipo", "nu,2"):
        with pytest.raises(ValueError, match="tik žodžiai"):
            config.coerce("FILLER_WORDS", bad)
    config.save({"FILLER_WORDS": "nu,žinai", "CLEAN_VIEW": "1"})
    c = config.load()
    assert c["FILLER_WORDS"] == "nu,žinai" and c["CLEAN_VIEW"] is True
    r = subprocess.run(["bash", "-c", f". '{env.conf_file}'; echo \"$FILLER_WORDS\""], capture_output=True, text=True)
    assert r.stdout.strip() == "nu,žinai"                                  # bash irgi perskaito


# ── Y3–Y4: transkripcijos ──

def day(n, hhmmss):
    return (datetime.now() - timedelta(days=n)).strftime("%Y%m%d") + "_" + hhmmss


@pytest.fixture
def data(env, tmp_path):
    from diktatura import sources
    r = env.recordings
    (r / f"slack_{day(1, '100000')}.named.txt").write_text(
        "[0:00:01] Jonas: migraciją darysim pirmadienį\n[0:00:09] Tu: ee, gerai\n[0:01:05] Ona: Mhm.\n", encoding="utf-8")
    (r / f"vox_{day(0, '090000')}.named.txt").write_text("[0:00:02] Tu: priminimas: migracijos planas\n",
                                                         encoding="utf-8")
    (r / f"rec_{day(0, '095000')}.txt").write_text("mono eilutė be laiko\n", encoding="utf-8")
    ph = tmp_path / "Telefonas"
    ph.mkdir()
    src = sources.add("Telefonas", ph)
    src.out_dir.mkdir(parents=True)
    base = src.out_dir / "Įrašas 7.m4a"
    sources.with_suffix(base, ".named.txt").write_text("[0:00:03] Tu: telefono pastaba apie migraciją\n",
                                                       encoding="utf-8")
    sources.with_suffix(base, ".src.json").write_text(json.dumps(
        {"audio": str(ph / "Įrašas 7.m4a"), "recorded": (datetime.now() - timedelta(days=2)).isoformat(),
         "source": "telefonas"}), encoding="utf-8")
    return env


def test_y3_load_filter_and_find(data):
    from diktatura import transcripts as T
    all_ = T.load_sessions()
    assert [s.id for s in all_] == ["telefonas/Įrašas 7.m4a", f"slack_{day(1, '100000')}", f"vox_{day(0, '090000')}",
                                    f"rec_{day(0, '095000')}"]
    assert [s.kind for s in all_] == ["Telefonas", "SLACK", "VOX", "REC"]
    assert [s.id for s in T.load_sessions(source="pokalbiai")][0].startswith("slack_")
    assert [s.id for s in T.load_sessions(source="Telefonas")] == [
        "telefonas/Įrašas 7.m4a"]
    assert len(T.load_sessions(since=date.today())) == 2
    assert len(T.load_sessions(until=date.today() - timedelta(days=1))) == 2
    s = T.find_session(f"slack_{day(1, '100000')}")
    assert s.speakers == ["Jonas", "Tu", "Ona"] and s.length == "0:01:05"
    assert T.find_session("telefonas/Įrašas 7.m4a").kind == "Telefonas"
    assert T.find_session("Įrašas 7.m4a") is not None and T.find_session("nėra") is None


def test_y4_search_speaker_regex_clean(data):
    from diktatura import transcripts as T
    hits, total = T.search("MIGRACIJ")
    assert total == 3 and [h[0].source for h in hits] == ["telefonas", "pokalbiai", "pokalbiai"]
    assert T.search("migracij", speaker="Jonas")[1] == 1
    assert T.search(r"pirmadien\w+|planas", regex=True)[1] == 2
    assert T.search("ee", clean=True)[1] == 0 and T.search("ee")[1] == 1
    hits, total = T.search("migracij", limit=1)
    assert total == 3 and len(hits) == 1
    assert T.format_line(T.Line("0:00:09", "Tu", "ee, gerai"), clean=True) == "[0:00:09] Tu: gerai"
    assert T.parse_date("vakar") == date.today() - timedelta(days=1) and T.parse_date(None) is None


# ── Y5–Y7: MCP serveris (tikras procesas, stdio) ──

def mcp(*msgs):
    lines = "\n".join(json.dumps(m, ensure_ascii=False) for m in msgs) + "\n"
    r = subprocess.run([str(REPO / "bin" / "mcp-server.sh")], input=lines, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return {m["id"]: m for m in map(json.loads, r.stdout.splitlines())}


def call(i, name, **args):
    return {"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": name, "arguments": args}}


def text(resp):
    return resp["result"]["content"][0]["text"]


def test_y5_handshake_and_tool_list(data):
    out = mcp({"jsonrpc": "2.0", "id": 1, "method": "initialize",
               "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}},
              {"jsonrpc": "2.0", "method": "notifications/initialized"},
              {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
              {"jsonrpc": "2.0", "id": 3, "method": "ping"},
              {"jsonrpc": "2.0", "id": 4, "method": "resources/list"})
    init = out[1]["result"]
    assert init["protocolVersion"] == "2025-03-26" and init["serverInfo"]["name"] == "diktatura"
    assert "tools" in init["capabilities"] and "Tu" in init["instructions"]
    assert [t["name"] for t in out[2]["result"]["tools"]] == ["list_sessions", "search", "get_transcript",
                                                               "speaker_stats", "list_sources"]
    assert all(t["inputSchema"]["type"] == "object" for t in out[2]["result"]["tools"])
    assert out[3]["result"] == {} and out[4]["error"]["code"] == -32601 and sorted(out) == [1, 2, 3, 4]


def test_y6_tools_read_transcripts(data):
    sid = f"slack_{day(1, '100000')}"
    out = mcp(call(1, "search", query="migracij", speaker="Jonas"),
              call(2, "get_transcript", session=sid, clean=True),
              call(3, "get_transcript", session=sid, start="0:00:05", end="0:00:10"),
              call(4, "list_sessions", source="Telefonas"),
              call(5, "speaker_stats", since="vakar"),
              call(6, "list_sources"))
    assert text(out[1]).startswith("Rasta: 1") and "Jonas: migraciją darysim pirmadienį" in text(out[1])
    t2 = text(out[2])
    assert "[0:00:09] Tu: gerai" in t2 and "Mhm" not in t2 and "SLACK" in t2.splitlines()[0]
    assert text(out[3]).splitlines()[1:] == ["[0:00:09] Tu: ee, gerai"]
    assert "telefonas/Įrašas 7.m4a" in text(out[4]) and "Sesijų: 1" in text(out[4])
    assert "- Tu:" in text(out[5]) and "Jonas" in text(out[5])
    assert "telefonas — „Telefonas\"" in text(out[6]) and "pokalbiai" in text(out[6])
    assert not any(o["result"]["isError"] for o in out.values())


def test_y7_errors_do_not_crash_server(data):
    out = mcp(call(1, "get_transcript", session="nėra_tokios"), call(2, "search", query=""),
              call(3, "list_sessions", since="2026-13-45"), call(4, "nežinomas"),
              {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "list_sources"}})
    assert out[1]["result"]["isError"] and "nėra" in text(out[1])
    assert out[2]["result"]["isError"] and out[3]["result"]["isError"]
    assert out[4]["error"]["code"] == -32602 and not out[5]["result"]["isError"]
    r = subprocess.run([str(REPO / "bin" / "mcp-server.sh")], input="ne json\n", capture_output=True, text=True,
                       timeout=30)
    assert json.loads(r.stdout)["error"]["code"] == -32700
