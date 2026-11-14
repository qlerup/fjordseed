"""Build the public, server-specific Userscripts installation source."""

import ipaddress
import json
from pathlib import Path
import re
from urllib.parse import urlencode, urlsplit


VERSION = "1.1.1"


def _authority(value):
    """Return a canonical host and explicit port without accepting URL syntax."""
    if not value or any(char.isspace() or ord(char) < 32 for char in value) or any(
            char in value for char in "/\\?#@%"):
        raise ValueError("Ugyldig FjordSeed-adresse.")
    try:
        parsed = urlsplit("http://" + value)
        hostname, port = parsed.hostname, parsed.port
        if (not hostname or parsed.username or parsed.password or value.endswith(":") or
                (port is not None and port < 1)):
            raise ValueError
        try:
            host = ipaddress.ip_address(hostname).compressed
        except ValueError:
            host = hostname.encode("idna").decode("ascii").lower()
            if (len(host) > 253 or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host) or
                    any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
                        for label in host.split(".")) or re.fullmatch(r"[0-9.]+", host)):
                raise ValueError
        return host, port
    except (ValueError, UnicodeError):
        raise ValueError("Ugyldig FjordSeed-adresse.") from None


def validate_seed_origin(value, request_host, request_scheme="http"):
    """Allow the visible browser scheme but only this request's exact authority.

    The scheme may differ behind a TLS reverse proxy. An omitted port means
    that scheme's default, so :443 and omitted HTTPS ports compare equally.
    Non-default ports must match and are retained in the generated script.
    """
    if value is None:
        value = request_scheme + "://" + request_host
    if (not isinstance(value, str) or len(value) > 2048 or not value or
            any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value) or
            "\\" in value):
        raise ValueError("Ugyldig FjordSeed-adresse.")
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in ("http", "https") or parsed.username or parsed.password or
                parsed.path not in ("", "/") or parsed.query or parsed.fragment or
                "?" in value or "#" in value):
            raise ValueError("Brug kun FjordSeeds grundadresse.")
        host, port = _authority(parsed.netloc)
        request_name, request_port = _authority(request_host)
        default = 443 if parsed.scheme == "https" else 80
        if host != request_name or (port if port is not None else default) != (request_port if request_port is not None else default):
            raise ValueError("Adressen skal høre til denne FjordSeed-server.")
        rendered_host = "[" + host + "]" if ":" in host else host
        authority = rendered_host + (":" + str(port) if port is not None and port != default else "")
        return parsed.scheme + "://" + authority
    except (ValueError, UnicodeError) as exc:
        raise ValueError(str(exc) or "Ugyldig FjordSeed-adresse.") from None


def build_userscript(seed_origin, root=None):
    """Assemble reviewed sources without Node, credentials or user session data."""
    root = Path(root) if root is not None else Path(__file__).resolve().parent
    parsed = urlsplit(seed_origin)
    seed_origin = validate_seed_origin(seed_origin, parsed.netloc, parsed.scheme)
    common = (root / "chrome-extension" / "common.mjs").read_text(encoding="utf-8")
    # Only this repository's known top-level declarations are converted.
    common = re.sub(r"(?m)^export (?=(?:const |function |async function ))", "", common)
    panel = (root / "safari-userscript" / "panel.js").read_text(encoding="utf-8")
    audio = (root / "safari-userscript" / "audio.js").read_text(encoding="utf-8")
    runtime = (root / "safari-userscript" / "runtime.js").read_text(encoding="utf-8")
    css = (root / "safari-userscript" / "panel.css").read_text(encoding="utf-8")
    if any(re.search(r"(?m)^\s*(?:import|export)\b", source) for source in (common, audio, panel, runtime)):
        raise RuntimeError("Userscript sources must not contain module imports or exports.")
    seed = urlsplit(seed_origin)
    host = "[" + seed.hostname + "]" if ":" in seed.hostname else seed.hostname
    install_url = seed_origin + "/browser/fjordseed.user.js?" + urlencode({"origin": seed_origin})
    metadata = [
        "// ==UserScript==",
        "// @name         FjordSeed · " + seed.netloc,
        "// @namespace    " + seed_origin,
        "// @version      " + VERSION,
        "// @description  Send torrentlinks og RSS fra NordicBytes og Sagmire til din FjordSeed.",
        "// @match        https://nordicbytes.org/*",
        "// @match        https://sagmire.org/*",
        "// @match        " + seed.scheme + "://" + host + "/*",
        "// @noframes",
        "// @inject-into  content",
        "// @run-at       document-idle",
        "// @grant        GM.getValue",
        "// @grant        GM.setValue",
        "// @grant        GM.deleteValue",
        "// @grant        GM.listValues",
        "// @grant        GM.openInTab",
        "// @updateURL    " + install_url,
        "// @downloadURL  " + install_url,
        "// ==/UserScript==",
    ]
    return ("\n".join(metadata) + "\n\n(async () => {\n" + common + "\n" + audio + "\n" + panel + "\n" + runtime +
            "\nawait startFjordSeedUserscript(" + json.dumps(seed_origin) + ", " + json.dumps(css) +
            ");\n})().catch(() => console.warn('FjordSeed kunne ikke starte. Genindlæs siden og prøv igen.'));\n")
