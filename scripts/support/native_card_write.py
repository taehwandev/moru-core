"""Effect-aware native card DML; only a quiet pre-write refusal permits replay.

Owner: NativeCardWrite. Allowed: stdlib, global state, NativeProbe availability.
Forbidden: schema/bootstrap changes, SQL mutation, generic probes or write retries.
Callers/tests: agent_work_cards; test_native_card_write proves effects/no replay.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from support.global_state import global_state_dir, user_store_write_error
from support.native_probe_transport import NativeProbe

_TIMEOUT = 10
_UNKNOWN = "native card write outcome is unknown; refusing to replay"
_PRIMARY_NAMES = (
    "OK ERROR INTERNAL PERM ABORT BUSY LOCKED NOMEM READONLY INTERRUPT IOERR "
    "CORRUPT NOTFOUND FULL CANTOPEN PROTOCOL EMPTY SCHEMA TOOBIG CONSTRAINT "
    "MISMATCH MISUSE NOLFS AUTH FORMAT RANGE NOTADB NOTICE WARNING"
).split()


def _sqlite_error(code, message):
    primary = code & 255
    if primary == 7:
        return MemoryError()
    kind = {2: sqlite3.InternalError, 12: sqlite3.InternalError,
            18: sqlite3.DataError, 19: sqlite3.IntegrityError,
            20: sqlite3.IntegrityError, 21: sqlite3.InterfaceError,
            25: sqlite3.InterfaceError}.get(primary, sqlite3.DatabaseError)
    if primary in (1, 3, 4, 5, 6, 8, 9, 10, 13, 14, 15, 16, 17):
        kind = sqlite3.OperationalError
    if sys.version_info < (3, 11) and primary in (21, 25):
        kind = sqlite3.ProgrammingError if primary == 21 else sqlite3.DatabaseError
    error = kind(message)
    if sys.version_info >= (3, 11):
        names = {i: "SQLITE_" + name for i, name in enumerate(_PRIMARY_NAMES)}
        for name in dir(sqlite3):
            # Exclude overlapping authorizer opcodes and SQLITE_LIMIT values.
            if any(name.startswith("SQLITE_" + base + "_") for base in _PRIMARY_NAMES[1:]):
                value = getattr(sqlite3, name)
                if type(value) is int and value > 255:
                    names[value] = name
        error.sqlite_errorcode = code
        error.sqlite_errorname = names.get(code, "unknown")
    return error


def _response(done, stdout, stderr):
    if done == 125 and not stdout and not stderr:
        return None  # The child guarantees every 125 occurs before DML.
    try:
        if done != 0 or stderr or len(stdout) > 65536:
            raise ValueError
        packet = json.loads(stdout, object_pairs_hook=_object)
        if (type(packet) is not dict or type(packet.get("schema_version")) is not int
                or packet["schema_version"] != 1):
            raise ValueError
        if set(packet) == {"schema_version", "result"}:
            result = packet["result"]
            if type(result) is dict and set(result) == {"changed"} and type(result["changed"]) is bool:
                return result["changed"]
        if set(packet) == {"schema_version", "error"}:
            error = packet["error"]
            if (type(error) is dict and set(error) == {"code", "message"}
                    and type(error["code"]) is int and 0 < error["code"] < (1 << 31)
                    and error["code"] & 255 and type(error["message"]) is str):
                return _sqlite_error(error["code"], error["message"])
        raise ValueError
    except (ValueError, TypeError, UnicodeError):
        raise sqlite3.OperationalError(_UNKNOWN) from None


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate native field")
        value[key] = item
    return value


def _eligible(connection, values):
    if (type(connection) is not sqlite3.Connection or connection.in_transaction
            or (str, sqlite3.PrepareProtocol) in sqlite3.adapters
            or any(type(value) is not str for value in values)
            or user_store_write_error() or not NativeProbe.available()):
        return False
    databases = connection.execute("PRAGMA database_list").fetchall()
    return (len(databases) == 1 and databases[0][1] == "main"
            and type(databases[0][2]) is str and bool(databases[0][2])
            and Path(databases[0][2]).resolve()
            == (global_state_dir() / "work-cards/cards.sqlite3").resolve())


def _request(connection, operation, values):
    # Every decline here precedes process creation and SQL mutation.
    try:
        if not _eligible(connection, values):
            return None
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        if type(foreign_keys) is not int or foreign_keys not in (0, 1):
            return None
        raw = json.dumps({"values": values, "foreign_keys": bool(foreign_keys)},
                         ensure_ascii=True, allow_nan=False).encode()
        if len(raw) > 65536:
            return None
        entry = Path.home() / ".moru/bin/moru-hook"
        command = [str(entry.with_name("moru-hook-native")), str(entry), "--cards-write-probe"]
        env = {**os.environ, "MORU_HOME": str(Path(__file__).resolve().parents[2])}
        # Old installed launchers do not recognize this effectful protocol.
        # Negotiate with a strictly read-only operation before starting a writer.
        ready = subprocess.run(command + ["ready"], capture_output=True, timeout=_TIMEOUT, env=env)
        if ready.returncode or ready.stderr or len(ready.stdout) > 65536:
            return None
        capability = json.loads(ready.stdout, object_pairs_hook=_object)
        if (type(capability) is not dict or set(capability) != {"schema_version", "ready"}
                or type(capability["schema_version"]) is not int or capability["schema_version"] != 1
                or capability["ready"] is not True):
            return None
        child = subprocess.Popen(
            command + [operation],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env)
    except (OSError, ValueError, RuntimeError, sqlite3.Error, subprocess.TimeoutExpired):
        return None
    # A started writer may have committed even if its response is lost.
    try:
        stdout, stderr = child.communicate(raw, timeout=_TIMEOUT)
    except BaseException as error:
        try:
            child.kill()
        except ProcessLookupError:
            pass
        child.communicate()
        if isinstance(error, (OSError, subprocess.TimeoutExpired)):
            raise sqlite3.OperationalError(_UNKNOWN) from None
        raise
    result = _response(child.returncode, stdout, stderr)
    if isinstance(result, BaseException):
        raise result
    return result


class NativeCardWrite:
    @staticmethod
    def open(connection, values, now, retention):
        if (type(now) is not datetime or (now.tzinfo is not None and now.tzinfo is not timezone.utc)
                or type(retention) is not timedelta or retention != timedelta(days=90)):
            return None
        result = _request(connection, "open", values)
        if result is False:
            raise sqlite3.OperationalError(_UNKNOWN)
        return result

    @staticmethod
    def settle(connection, values):
        return _request(connection, "settle", values)
