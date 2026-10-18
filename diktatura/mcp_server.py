"""Diktatūra — MCP serveris (Model Context Protocol, stdio): AI klientas (pvz. Claude Code) gali ieškoti tavo
transkripcijose — „ką vakar sakė Jonas apie migraciją?". Tik stdlib, TIK SKAITO.

Įrankiai: list_sessions, search, get_transcript, speaker_stats, list_sources (pokalbiai + sekami aplankai).
Privatumas: serveris pats niekur nejungia ir nieko nesiunčia — jis tik atsako klientui, kuris jį paleido. Bet ką
klientas perskaito, tas patenka į jo pokalbį: debesų AI (Claude) atveju — į jo debesį. Todėl prijungiama tik
savininkui pačiam nusprendus (make mcp parodo komandą; automatiškai niekur neregistruojama).
Paleidimas: bin/mcp-server.sh  (JSON-RPC 2.0 po vieną žinutę eilutėje stdin / stdout).
"""
import json
import sys

from diktatura import sessions, transcripts

NAME, VERSION = "diktatura", "1.0"
PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
MAX_LINES = 1500

DATE = {"type": "string", "description": "Data YYYY-MM-DD (arba „šiandien\", „vakar\")"}
SOURCE = {"type": "string", "description": "„pokalbiai\" (VOX / Slack įrašai), sekamo aplanko id ar pavadinimas "
                                           "(pvz. „Telefonas\"); nenurodžius — visi"}
TOOLS = [
    {"name": "list_sessions", "description": "Transkribuotų sesijų sąrašas (naujausios pirmos): id, laikas, šaltinis, "
                                             "trukmė, eilučių skaičius, kalbėtojai.",
     "inputSchema": {"type": "object", "properties": {"since": DATE, "until": DATE, "source": SOURCE,
                                                      "limit": {"type": "integer", "default": 30}}}},
    {"name": "search", "description": "Paieška transkripcijose (be didžiųjų/mažųjų raidžių skirtumo): eilutės su laiku, "
                                      "kalbėtoju ir sesija. Lietuviškai — ieškok žodžio šaknies (pvz. „migracij\").",
     "inputSchema": {"type": "object", "required": ["query"], "properties": {
         "query": {"type": "string"}, "regex": {"type": "boolean", "default": False},
         "speaker": {"type": "string", "description": "tik šio kalbėtojo eilutės (pvz. „Jonas\", „Tu\")"},
         "since": DATE, "until": DATE, "source": SOURCE, "limit": {"type": "integer", "default": 30},
         "clean": {"type": "boolean", "default": False, "description": "be užpildų (ee, mhm…)"}}}},
    {"name": "get_transcript", "description": "Visas sesijos tekstas (ar jo dalis pagal laiką). Sesijos id — iš "
                                              "list_sessions / search.",
     "inputSchema": {"type": "object", "required": ["session"], "properties": {
         "session": {"type": "string"}, "start": {"type": "string", "description": "nuo H:MM:SS"},
         "end": {"type": "string", "description": "iki H:MM:SS"},
         "clean": {"type": "boolean", "default": False, "description": "be užpildų (ee, mhm…)"}}}},
    {"name": "speaker_stats", "description": "Kas kiek kalbėjo (eilutės, žodžiai, ≈ laikas) per laikotarpį.",
     "inputSchema": {"type": "object", "properties": {"since": DATE, "until": DATE, "source": SOURCE}}},
    {"name": "list_sources", "description": "Šaltiniai: pokalbiai (VOX / Slack) ir sekami aplankai (telefonas, "
                                            "laikrodis…) su tekstų skaičiumi.",
     "inputSchema": {"type": "object", "properties": {}}},
]
INSTRUCTIONS = ("Diktatūra — lietuviškos pokalbių ir diktavimo transkripcijos (Slack skambučiai, diktavimas, telefono "
                "įrašai). Eilutės: [H:MM:SS] Kalbėtojas: tekstas; „Tu\" — savininkas, „Kolega?\" — neatpažintas balsas. "
                "Pirma search arba list_sessions, tada get_transcript reikiamai daliai.")


def _date(args, key):
    return transcripts.parse_date(args.get(key))


def _head(s) -> str:
    return f"{s.id} · {s.when:%Y-%m-%d %H:%M} · {s.kind or s.source}"


def tool_list_sessions(a) -> str:
    sess = transcripts.load_sessions(_date(a, "since"), _date(a, "until"), a.get("source"))
    limit = max(1, int(a.get("limit") or 30))
    shown = list(reversed(sess))[:limit]
    out = [f"Sesijų: {len(sess)}" + (f" (rodoma {len(shown)} naujausių)" if len(shown) < len(sess) else "")]
    for s in shown:
        out.append(f"- {_head(s)}" + (f" · {s.length}" if s.length else "") + f" · {len(s.lines)} eil."
                   + (f" · {', '.join(s.speakers)}" if s.speakers else ""))
    return "\n".join(out)


def tool_search(a) -> str:
    q = str(a.get("query") or "").strip()
    if not q:
        raise ValueError("tuščia paieška")
    limit = max(1, int(a.get("limit") or 30))
    hits, total = transcripts.search(q, bool(a.get("regex")), _date(a, "since"), _date(a, "until"), a.get("speaker"),
                                     a.get("source"), limit, bool(a.get("clean")))
    if not total:
        return f"Nerasta: „{q}\"."
    out = [f"Rasta: {total}" + (f" (rodoma {len(hits)})" if len(hits) < total else "")]
    for s, ln in hits:
        out.append(f"[{_head(s)}] {transcripts.format_line(ln)}")
    return "\n".join(out)


def tool_get_transcript(a) -> str:
    sid = str(a.get("session") or "").strip()
    s = transcripts.find_session(sid)
    if s is None:
        raise ValueError(f"sesijos „{sid}\" nėra (žr. list_sessions)")
    lo = sessions.ts_seconds(a["start"]) if a.get("start") else None
    hi = sessions.ts_seconds(a["end"]) if a.get("end") else None
    lines = [ln for ln in s.lines if (lo is None or (ln.seconds or 0) >= lo) and (hi is None or (ln.seconds or 0) <= hi)]
    out = [f"{_head(s)}" + (f" · {s.length}" if s.length else "") + (f" · {', '.join(s.speakers)}" if s.speakers else "")]
    out += [transcripts.format_line(ln, bool(a.get("clean"))) for ln in lines[:MAX_LINES]]
    if len(lines) > MAX_LINES:
        out.append(f"… (dar {len(lines) - MAX_LINES} eil. — nurodyk start / end)")
    return "\n".join(out)


def tool_speaker_stats(a) -> str:
    sess = transcripts.load_sessions(_date(a, "since"), _date(a, "until"), a.get("source"))
    st = transcripts.stats(sess)
    if not st:
        return "Per šį laikotarpį tekstų nėra."
    total = sum(v["seconds"] for v in st.values()) or 1
    out = [f"Sesijų: {len(sess)}. Kalbėtojas — eilučių, žodžių, ≈ laikas, dalis:"]
    for name, v in sorted(st.items(), key=lambda kv: -kv[1]["seconds"]):
        m, sec = divmod(int(v["seconds"]), 60)
        out.append(f"- {name}: {v['lines']}, {v['words']}, {m // 60}:{m % 60:02d}:{sec:02d}, "
                   f"{100 * v['seconds'] / total:.0f} %")
    return "\n".join(out)


def tool_list_sources(_a) -> str:
    from diktatura import paths, sources
    out = [f"- pokalbiai — VOX / Slack įrašai ({len(sessions.text_files(paths.RECORDINGS))} tekstų)"]
    for s in sources.load():
        n = len(sessions.text_files(s.out_dir)) if s.out_dir.exists() else 0
        out.append(f"- {s.id} — „{s.name}\" ({s.path}; {n} tekstų{'' if s.enabled else ', nesekamas'})")
    return "\n".join(out)


HANDLERS = {"list_sessions": tool_list_sessions, "search": tool_search, "get_transcript": tool_get_transcript,
            "speaker_stats": tool_speaker_stats, "list_sources": tool_list_sources}


def handle(msg: dict):
    """Viena JSON-RPC žinutė -> atsakymas (dict) arba None (pranešimui atsakymo nereikia)."""
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if mid is None:
        return None                                                  # notifications/initialized ir pan.
    if method == "initialize":
        want = params.get("protocolVersion")
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": want if want in PROTOCOLS else PROTOCOLS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": NAME, "version": VERSION}, "instructions": INSTRUCTIONS}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        fn = HANDLERS.get(name)
        if fn is None:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"nežinomas įrankis: {name}"}}
        try:
            text, err = fn(args), False
        except (ValueError, KeyError, TypeError) as e:
            text, err = f"Klaida: {e}", True
        except Exception as e:                                       # serveris nelūžta dėl vieno failo
            text, err = f"Vidinė klaida: {type(e).__name__}: {e}", True
        return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}], "isError": err}}
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"nežinomas metodas: {method}"}}


def serve(inp=sys.stdin, out=sys.stdout) -> int:
    for raw in inp:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except ValueError:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "netinkamas JSON"}}
        else:
            msgs = msg if isinstance(msg, list) else [msg]
            resps = [r for r in (handle(m) for m in msgs if isinstance(m, dict)) if r is not None]
            resp = resps if isinstance(msg, list) else (resps[0] if resps else None)
        if resp:
            out.write(json.dumps(resp, ensure_ascii=False) + "\n")
            out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(serve())
