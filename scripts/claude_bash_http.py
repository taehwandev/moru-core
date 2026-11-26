"""Classify explicit HTTP reads, independently of provider and credentials.

This is an effect classifier, not network authorization or an assertion that a
server implements GET correctly. Unknown options retain normal write checks.
"""

import os
from pathlib import Path
from urllib.parse import urlsplit


LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
PROXY_ENV_VARS = (
    "http_proxy",
    "HTTP_PROXY",
    "https_proxy",
    "HTTPS_PROXY",
    "all_proxy",
    "ALL_PROXY",
)


def _has_proxy_env() -> bool:
    """Whether any curl proxy environment variable is set."""
    return any(os.environ.get(var, "").strip() for var in PROXY_ENV_VARS)


def _has_implicit_curlrc() -> bool:
    """Whether curl could load an implicit curlrc when `-q`/`--disable` is omitted."""
    candidates: list[Path] = []
    curl_home = os.environ.get("CURL_HOME", "").strip()
    if curl_home:
        candidates.append(Path(curl_home).expanduser() / ".curlrc")
    xdg_config = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if xdg_config:
        xdg_dir = Path(xdg_config).expanduser()
        candidates.append(xdg_dir / "curlrc")
        candidates.append(xdg_dir / ".curlrc")
    home = Path.home()
    candidates.append(home / ".curlrc")
    candidates.append(home / ".config" / "curlrc")
    candidates.append(home / ".config" / ".curlrc")
    for candidate in candidates:
        try:
            if candidate.exists() or candidate.is_symlink():
                return True
        except OSError:
            return True
    return False


def curl_read_only(args: list[str]) -> bool:
    """Accept GET/HEAD to stdout without hidden curlrc actions or output files."""
    return curl_effect(args)[0] == "read_only"


def curl_effect(args: list[str]) -> tuple[str, str]:
    """Explain unsupported input separately from a recognized request/file write."""
    if not args:
        return "unknown", "missing or unsupported HTTP URL"
    has_disable_first = args[0] in {"-q", "--disable"}
    flags = {"--silent", "--show-error", "--fail", "--fail-with-body",
             "--location", "--head", "--include", "--compressed", "--ipv4", "--ipv6",
             "--no-progress-meter", "--globoff", "--get"}
    values = {"--header", "--user", "--connect-timeout", "--max-time",
              "--retry", "--retry-delay", "--retry-max-time", "--user-agent",
              "--cacert", "--capath", "--proxy", "--noproxy", "--write-out"}
    short_flags = set("sSfLIigG46")
    short_values = {"H", "u", "A", "m", "x", "w"}
    writes = {"--upload-file", "--form", "--form-string", "--remote-name",
              "--remote-name-all", "--dump-header", "--trace", "--trace-ascii",
              "--cookie-jar", "--alt-svc", "--hsts", "--libcurl",
              "--data", "--data-raw", "--data-binary", "--data-urlencode", "--json"}
    urls = []
    used_proxy = False
    index = 1 if has_disable_first else 0
    while index < len(args):
        token = args[index]
        index += 1
        option, equals, value = token.partition("=")
        if token == "--":
            urls.extend(args[index:])
            break
        if option.startswith("--"):
            if option in writes:
                return "mutating", "curl upload or file-output option"
            if option in flags and not equals:
                continue
            if option not in values | {"--request", "--url", "--output"}:
                return "unknown", "curl option has no verified effect contract"
            if option == "--proxy":
                used_proxy = True
            if not equals:
                if index == len(args):
                    return "unknown", "curl option is missing its value"
                value = args[index]
                index += 1
            effect = _value_effect(option, value, urls)
            if effect != "read_only":
                return effect, "curl method or output destination is not a verified read"
        elif token.startswith("-"):
            cluster = token[1:]
            if not cluster:
                return "unknown", "incomplete curl option"
            while cluster:
                flag, cluster = cluster[0], cluster[1:]
                if flag in short_flags:
                    continue
                if flag in {"T", "F", "O", "D", "c", "d"}:
                    return "mutating", "curl upload or file-output option"
                if flag not in short_values | {"X", "o"}:
                    return "unknown", "curl option has no verified effect contract"
                if flag == "x":
                    used_proxy = True
                value = cluster
                if not value:
                    if index == len(args):
                        return "unknown", "curl option is missing its value"
                    value = args[index]
                    index += 1
                option = {"X": "--request", "o": "--output", "w": "--write-out"}.get(
                    flag, "--value"
                )
                effect = _value_effect(option, value, urls)
                if effect != "read_only":
                    return effect, "curl method or output destination is not a verified read"
                break
        else:
            urls.append(token)
    if not urls:
        return "unknown", "missing or unsupported HTTP URL"
    if not has_disable_first:
        # Localhost/loopback GET/HEAD probes may omit -q only when no proxy option
        # or proxy environment variable is set and no implicit curlrc exists.
        if used_proxy or _has_proxy_env():
            return "unknown", "curl proxy option or proxy env may change request behavior; put -q first"
        if not _has_implicit_curlrc() and all(_loopback_http_url(url) for url in urls):
            return "read_only", ""
        return "unknown", "implicit curl configuration may change request or output behavior; put -q first"
    if not all(_http_url(url) for url in urls):
        return "unknown", "missing or unsupported HTTP URL"
    return "read_only", ""


def _value_effect(option: str, value: str, urls: list[str]) -> str:
    if not value:
        return "unknown"
    if option == "--request":
        if value in {"GET", "HEAD"}:
            return "read_only"
        return "mutating" if value in {"POST", "PUT", "PATCH", "DELETE"} else "unknown"
    if option == "--output":
        # stdout, or the discard sink a probe sends the body to while it prints
        # only a status line. A scratch target reaches here as the sink too.
        return "read_only" if value in {"-", "/dev/null"} else "mutating"
    if option == "--write-out":
        # The format prints to stdout, except `%output{file}`, which writes.
        return "mutating" if "%output{" in value else "read_only"
    if option == "--url":
        urls.append(value)
    return "read_only"


def _http_url(value: str) -> bool:
    try:
        url = urlsplit(value)
        return url.scheme.lower() in {"http", "https"} and bool(url.hostname)
    except ValueError:
        return False


def _loopback_http_url(value: str) -> bool:
    candidate = value
    if "://" not in candidate:
        if candidate.startswith(("127.0.0.1", "localhost", "[::1]")):
            candidate = "http://" + candidate
        else:
            return False
    try:
        url = urlsplit(candidate)
        return url.scheme.lower() in {"http", "https"} and (url.hostname or "").lower() in LOOPBACK_HOSTS
    except ValueError:
        return False
