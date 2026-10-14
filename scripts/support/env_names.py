"""Read Moru environment settings while the legacy ``TAO_`` names still resolve.

Every setting is named ``MORU_*``. During the rename window a process may still
be started with the old ``TAO_*`` spelling -- a hook command written by an
earlier setup, a shell profile, a running agent that read its environment
before the rename -- so a read falls back to that spelling when the Moru one is
absent. Writers set only the Moru name; nothing new is written under ``TAO_``.
"""

from __future__ import annotations

import os

PREFIX = "MORU_"
LEGACY_PREFIX = "TAO_"


def legacy_name(name: str) -> str:
    """The ``TAO_`` spelling of a ``MORU_`` setting name."""

    if name.startswith(PREFIX):
        return LEGACY_PREFIX + name[len(PREFIX):]
    return name


def env_get(name: str, default: str = "") -> str:
    """The value of ``name``, else its legacy spelling, else ``default``."""

    value = os.environ.get(name)
    if value is None:
        value = os.environ.get(legacy_name(name))
    return default if value is None else value


def env_is_set(name: str) -> bool:
    return name in os.environ or legacy_name(name) in os.environ
