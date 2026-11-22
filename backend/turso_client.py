"""Cliente HTTP ligero para Turso / libSQL (/v2/pipeline · protocolo Hrana v2).

Implementa una interfaz compatible con `sqlite3.Connection` (`execute`, `executemany`,
`executescript`, `commit`, `close`, `Row` con acceso por índice y por nombre, `lastrowid`)
utilizando únicamente `httpx` (ya presente en requirements.txt), sin dependencias binarias
que puedan fallar o superar límites en Vercel Serverless.
"""
from __future__ import annotations

import base64
import math
import re
import threading
from typing import Any, Iterable, Sequence

import httpx


class TursoError(RuntimeError):
    """Error devuelto por la API HTTP de Turso / libSQL."""


def normalize_pipeline_url(database_url: str) -> str:
    raw = (database_url or "").strip().rstrip("/")
    if not raw:
        raise ValueError("TURSO_DATABASE_URL está vacía")
    if raw.startswith("libsql://"):
        base = "https://" + raw[len("libsql://"):]
    elif raw.startswith("wss://"):
        base = "https://" + raw[len("wss://"):]
    elif raw.startswith("ws://"):
        base = "http://" + raw[len("ws://"):]
    elif raw.startswith(("https://", "http://")):
        base = raw
    else:
        base = "https://" + raw
    if base.endswith("/v2/pipeline"):
        return base
    return f"{base}/v2/pipeline"


def _encode_arg(value: Any) -> dict[str, Any]:
    """Codifica un parámetro Python al formato tipado de Hrana v2."""
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": "1" if value else "0"}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return {"type": "null"}
        return {"type": "float", "value": float(value)}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"type": "blob", "base64": base64.b64encode(bytes(value)).decode("ascii")}
    return {"type": "text", "value": str(value)}


def _decode_cell(cell: dict[str, Any]) -> Any:
    ctype = cell.get("type")
    if ctype == "null" or ctype is None:
        return None
    if ctype == "integer":
        return int(cell["value"])
    if ctype == "float":
        return float(cell["value"])
    if ctype == "text":
        return str(cell.get("value", ""))
    if ctype == "blob":
        return base64.b64decode(cell.get("base64", ""))
    return cell.get("value")


class TursoRow:
    """Fila compatible con `sqlite3.Row` (acceso por índice, clave y `dict(row)`)."""

    __slots__ = ("_cols", "_vals", "_map")

    def __init__(self, cols: tuple[str, ...], vals: tuple[Any, ...]):
        self._cols = cols
        self._vals = vals
        self._map = dict(zip(cols, vals))

    def __getitem__(self, key: int | str) -> Any:
        if isinstance(key, int):
            return self._vals[key]
        return self._map[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._map.get(key, default)

    def keys(self) -> list[str]:
        return list(self._cols)

    def __contains__(self, key: object) -> bool:
        return key in self._map

    def __iter__(self):
        return iter(self._vals)

    def __len__(self) -> int:
        return len(self._vals)

    def __repr__(self) -> str:
        return f"TursoRow({self._map!r})"


class TursoCursor:
    """Cursor compatible con el subconjunto de `sqlite3.Cursor` usado por GameHub."""

    def __init__(
        self,
        rows: list[TursoRow],
        *,
        lastrowid: int | None = None,
        rowcount: int = -1,
    ):
        self._rows = rows
        self._idx = 0
        self.lastrowid = lastrowid
        self.rowcount = rowcount

    def fetchone(self) -> TursoRow | None:
        if self._idx >= len(self._rows):
            return None
        row = self._rows[self._idx]
        self._idx += 1
        return row

    def fetchall(self) -> list[TursoRow]:
        out = self._rows[self._idx:]
        self._idx = len(self._rows)
        return out

    def __iter__(self):
        return iter(self.fetchall())


def split_sql_script(script: str) -> list[str]:
    """Divide un script SQL en sentencias respetando bloques BEGIN ... END; de triggers y cadenas."""
    stmts: list[str] = []
    buf: list[str] = []
    in_single = False
    in_double = False
    in_line_comment = False
    in_block_comment = False
    trigger_depth = 0
    i = 0
    n = len(script)

    while i < n:
        ch = script[i]
        nxt = script[i + 1] if i + 1 < n else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue

        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
            else:
                i += 1
            continue

        if in_single:
            buf.append(ch)
            if ch == "'" and nxt == "'":
                buf.append(nxt)
                i += 2
                continue
            if ch == "'":
                in_single = False
            i += 1
            continue

        if in_double:
            buf.append(ch)
            if ch == '"':
                in_double = False
            i += 1
            continue

        if ch == "-" and nxt == "-":
            in_line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        if ch == "'":
            in_single = True
            buf.append(ch)
            i += 1
            continue
        if ch == '"':
            in_double = True
            buf.append(ch)
            i += 1
            continue

        # Detectar BEGIN / END en triggers para no cortar en el ';' interior
        if ch.isalpha():
            m = re.match(r"[A-Za-z_]+", script[i:])
            if m:
                word = m.group(0)
                upper = word.upper()
                prev_ch = script[i - 1] if i > 0 else " "
                if not (prev_ch.isalnum() or prev_ch == "_"):
                    if upper == "BEGIN":
                        trigger_depth += 1
                    elif upper == "END" and trigger_depth > 0:
                        trigger_depth -= 1
                buf.append(word)
                i += len(word)
                continue

        if ch == ";" and trigger_depth == 0:
            candidate = "".join(buf).strip()
            if candidate:
                stmts.append(candidate)
            buf = []
            i += 1
            continue

        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        stmts.append(tail)
    return stmts


_client_lock = threading.Lock()
_clients: dict[tuple[str, str], httpx.Client] = {}
_override_transport: httpx.BaseTransport | None = None


def set_test_transport(transport: httpx.BaseTransport | None) -> None:
    """Permite inyectar un `httpx.MockTransport` en tests unitarios."""
    global _override_transport
    with _client_lock:
        for cli in _clients.values():
            try:
                cli.close()
            except Exception:
                pass
        _clients.clear()
        _override_transport = transport


def _get_http_client(pipeline_url: str, auth_token: str) -> httpx.Client:
    key = (pipeline_url, auth_token)
    with _client_lock:
        cli = _clients.get(key)
        if cli is not None and not cli.is_closed:
            return cli
        headers = {
            "Authorization": f"Bearer {auth_token}",
            "Content-Type": "application/json",
            "User-Agent": "GameHub-TursoHTTP/1.0",
        }
        cli = httpx.Client(
            headers=headers,
            timeout=httpx.Timeout(20.0, connect=8.0),
            transport=_override_transport,
        )
        _clients[key] = cli
        return cli


class TursoConnection:
    """Conexión lógica sobre la API HTTP `/v2/pipeline` de Turso / libSQL."""

    def __init__(self, database_url: str, auth_token: str):
        self.pipeline_url = normalize_pipeline_url(database_url)
        self.auth_token = auth_token

    def _build_stmt(self, sql: str, params: Sequence[Any] | None = None) -> dict[str, Any]:
        stmt: dict[str, Any] = {"sql": sql}
        if params:
            stmt["args"] = [_encode_arg(p) for p in params]
        return stmt

    def _run_pipeline(self, stmts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not stmts:
            return []
        requests: list[dict[str, Any]] = [
            {"type": "execute", "stmt": s} for s in stmts
        ]
        requests.append({"type": "close"})

        cli = _get_http_client(self.pipeline_url, self.auth_token)
        resp = cli.post(self.pipeline_url, json={"requests": requests})
        if resp.status_code >= 400:
            raise TursoError(f"Turso HTTP {resp.status_code}: {resp.text[:260]}")

        payload = resp.json() or {}
        results = payload.get("results") or []
        parsed_results: list[dict[str, Any]] = []

        for idx, entry in enumerate(results[: len(stmts)]):
            if entry.get("type") == "error":
                err_msg = ((entry.get("error") or {}).get("message")) or str(entry)
                raise TursoError(f"Error SQL Turso (sentencia #{idx + 1}): {err_msg}")
            res_obj = ((entry.get("response") or {}).get("result")) or {}
            parsed_results.append(res_obj)
        return parsed_results

    @staticmethod
    def _result_to_cursor(res_obj: dict[str, Any]) -> TursoCursor:
        cols = tuple(str(c.get("name") or f"col_{i}") for i, c in enumerate(res_obj.get("cols") or []))
        rows: list[TursoRow] = []
        for raw_row in res_obj.get("rows") or []:
            vals = tuple(_decode_cell(cell) for cell in raw_row)
            rows.append(TursoRow(cols, vals))
        raw_lid = res_obj.get("last_insert_rowid")
        lastrowid = int(raw_lid) if raw_lid not in (None, "") else None
        rowcount = int(res_obj.get("affected_row_count", 0))
        return TursoCursor(rows, lastrowid=lastrowid, rowcount=rowcount)

    def execute(self, sql: str, params: Sequence[Any] = ()) -> TursoCursor:
        results = self._run_pipeline([self._build_stmt(sql, params)])
        if not results:
            return TursoCursor([])
        return self._result_to_cursor(results[0])

    def executemany(self, sql: str, seq_of_params: Iterable[Sequence[Any]], chunk_size: int = 80) -> TursoCursor:
        batch = list(seq_of_params)
        if not batch:
            return TursoCursor([], rowcount=0)
        total_affected = 0
        last_lid: int | None = None

        for i in range(0, len(batch), chunk_size):
            chunk = batch[i : i + chunk_size]
            stmts: list[dict[str, Any]] = []
            use_tx = len(chunk) > 1
            if use_tx:
                stmts.append({"sql": "BEGIN"})
            for p in chunk:
                stmts.append(self._build_stmt(sql, p))
            if use_tx:
                stmts.append({"sql": "COMMIT"})

            results = self._run_pipeline(stmts)
            inner = results[1:-1] if use_tx else results
            for r in inner:
                total_affected += int(r.get("affected_row_count", 0))
                if r.get("last_insert_rowid") not in (None, ""):
                    last_lid = int(r["last_insert_rowid"])

        return TursoCursor([], lastrowid=last_lid, rowcount=total_affected)

    def execute_batch(self, statements: Sequence[str | tuple[str, Sequence[Any]]]) -> list[TursoCursor]:
        stmts: list[dict[str, Any]] = []
        for item in statements:
            if isinstance(item, tuple):
                sql, params = item
                stmts.append(self._build_stmt(sql, params))
            else:
                s = str(item).strip()
                if s:
                    stmts.append(self._build_stmt(s))
        if not stmts:
            return []
        results = self._run_pipeline(stmts)
        return [self._result_to_cursor(r) for r in results]

    def executescript(self, script: str) -> None:
        stmts = [
            s for s in split_sql_script(script)
            if not s.upper().startswith("PRAGMA JOURNAL_MODE")
        ]
        self.execute_batch(stmts)

    def commit(self) -> None:
        # Cada pipeline HTTP confirma sus sentencias automáticamente
        return

    def close(self) -> None:
        return
