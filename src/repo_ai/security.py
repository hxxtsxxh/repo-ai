"""Secret detection.

Design rules, in priority order:

1. **Never store a secret value.** Findings carry a redacted fingerprint only
   (first 4 chars + length). The value never reaches the index, the generated
   docs, hook output, logs, or the agent's context.
2. **Path rules beat content rules.** `.env`, `*.pem`, `credentials.json` and
   friends are quarantined on name alone, before the file is ever read.
3. **Quarantine key material; report the rest.** A content hit from a rule in
   `QUARANTINE_RULES` (an embedded private key, an AWS secret key) removes the
   whole file from the index and adds it to the agent ignore lists. Every other
   high-severity hit is *reported* in SECURITY_NOTES.md but the file stays
   indexed: over-quarantining silently degrades context, and a listed finding
   a human can act on beats a silent hole.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import PurePosixPath

from .models import SecretHit

# --------------------------------------------------------------------------
# High-confidence provider tokens. Prefixes are distinctive enough that a
# match is almost never a false positive.
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Rule:
    name: str
    pattern: re.Pattern[str]
    severity: str
    entropy_floor: float = 0.0


HIGH_CONFIDENCE_RULES: tuple[Rule, ...] = (
    Rule("aws-access-key-id", re.compile(r"\b((?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16})\b"), "high"),
    Rule("aws-secret-access-key", re.compile(
        r"(?i)aws.{0,20}?(?:secret|private).{0,20}?['\"]([A-Za-z0-9/+=]{40})['\"]"), "high"),
    Rule("github-token", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{36,255})\b"), "high"),
    Rule("github-fine-grained", re.compile(r"\b(github_pat_[A-Za-z0-9_]{22,255})\b"), "high"),
    Rule("gitlab-token", re.compile(r"\b(glpat-[A-Za-z0-9_\-]{20,})\b"), "high"),
    Rule("slack-token", re.compile(r"\b(xox[baprs]-[A-Za-z0-9-]{10,})\b"), "high"),
    Rule("slack-webhook", re.compile(r"(https://hooks\.slack\.com/services/[A-Za-z0-9/]{20,})"), "high"),
    Rule("stripe-key", re.compile(r"\b((?:sk|rk)_(?:live|test)_[A-Za-z0-9]{20,})\b"), "high"),
    Rule("google-api-key", re.compile(r"\b(AIza[0-9A-Za-z_\-]{35})\b"), "high"),
    Rule("google-oauth", re.compile(r"\b([0-9]+-[0-9a-z_]{32}\.apps\.googleusercontent\.com)\b"), "medium"),
    # `sk-ant-` belongs to Anthropic; exclude it so one key is one finding.
    Rule("openai-key", re.compile(r"\b(sk-(?!ant-)(?:proj-)?[A-Za-z0-9_\-]{20,})\b"), "high"),
    Rule("anthropic-key", re.compile(r"\b(sk-ant-[A-Za-z0-9_\-]{20,})\b"), "high"),
    Rule("ibm-cloud-key", re.compile(r"(?i)ibm.{0,15}(?:api)?key.{0,10}['\"]([A-Za-z0-9_\-]{40,50})['\"]"), "high"),
    Rule("npm-token", re.compile(r"\b(npm_[A-Za-z0-9]{36})\b"), "high"),
    Rule("pypi-token", re.compile(r"\b(pypi-[A-Za-z0-9_\-]{50,})\b"), "high"),
    Rule("sendgrid-key", re.compile(r"\b(SG\.[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{16,})\b"), "high"),
    Rule("twilio-sid", re.compile(r"\b(AC[0-9a-fA-F]{32})\b"), "medium"),
    Rule("private-key-block", re.compile(
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY-----"), "high"),
    Rule("jwt", re.compile(r"\b(eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,})\b"), "medium"),
    Rule("connection-string", re.compile(
        r"\b((?:postgres|postgresql|mysql|mongodb(?:\+srv)?|redis|amqp|mssql)://"
        r"[^\s:@/]{1,64}:[^\s:@/]{3,120}@[^\s/]{3,})"), "high"),
    Rule("azure-storage-key", re.compile(
        r"(?i)accountkey\s*=\s*([A-Za-z0-9+/=]{60,})"), "high"),
)

# Generic `SECRET = "..."` assignments. Gated on entropy to cut false positives.
GENERIC_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_\-]?key|apikey|secret|passwd|password|passphrase|token|"
    r"auth[_\-]?token|access[_\-]?token|refresh[_\-]?token|client[_\-]?secret|"
    r"private[_\-]?key|encryption[_\-]?key|signing[_\-]?key|credential)s?\b"
    r"\s*[:=]\s*"
    r"['\"]([^'\"\s]{12,120})['\"]"
)

# Values that look like secrets but are obviously placeholders.
PLACEHOLDER_RE = re.compile(
    r"(?i)^(?:x{3,}|y{3,}|\*{3,}|\.{3,}|<[^>]+>|\$\{[^}]+\}|\{\{[^}]+\}\}|"
    r"%[a-z_]+%|process\.env\.|os\.environ|null|none|true|false|undefined|"
    r"changeme|change[_\-]?me|your[_\-]?|my[_\-]?|example|sample|dummy|"
    r"placeholder|redacted|insert|todo|fixme|test[_\-]?key|fake|foo|bar|baz|"
    r"password|secret|123|abc)"
)

PLACEHOLDER_CONTAINS = re.compile(
    r"(?i)(example|placeholder|dummy|redacted|xxxxx|change[_-]?me|your[_-]?key|"
    r"insert[_-]?here|not[_-]?a[_-]?real|sample|template)"
)

# Files where a "secret" is expected to be a documented example.
DOC_LIKE_RE = re.compile(
    r"(?i)(readme|contributing|changelog|\.md$|\.mdx$|\.rst$|docs?/|examples?/|samples?/"
    r"|\.(example|sample|template|dist|tpl)$|\.env\.(example|sample|template))")


def shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = Counter(value)
    length = len(value)
    return -sum((c / length) * math.log2(c / length) for c in counts.values())


def _redact(value: str) -> str:
    value = value.strip()
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:4]}{'*' * min(len(value) - 4, 24)} (len={len(value)})"


# Vendor-published example credentials. Matching these exactly is safe;
# suppressing on a fuzzy "contains the word example" rule is not, because a
# real key can contain those characters.
KNOWN_EXAMPLE_VALUES: frozenset[str] = frozenset({
    "AKIAIOSFODNN7EXAMPLE",
    "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    "ASIAIOSFODNN7EXAMPLE",
    "AIzaSyDaGmWKa4JsXZ-HjGw7ISLn_3namBGewQe",
})

# Credential-shaped strings whose *value* is obviously a stand-in.
_WEAK_SECRET_VALUES = frozenset({
    "pass", "password", "passwd", "secret", "user", "username", "admin",
    "root", "test", "example", "changeme", "mypassword", "yourpassword",
    "hunter2", "letmein", "postgres", "mysql", "redis", "guest",
})


_DEV_PASSWORD_MARKERS = re.compile(
    r"(?i)(local|dev|devel|test|demo|fake|dummy|sample|example|placeholder|"
    r"changeme|password|passwd|secret|admin|root|postgres|mysql|redis|mongo)"
)

# Hostnames that only resolve inside a developer's machine or compose network.
_LOCAL_HOSTS = frozenset({
    "localhost", "127.0.0.1", "0.0.0.0", "::1", "host.docker.internal",
    "db", "database", "postgres", "postgresql", "mysql", "mariadb",
    "redis", "mongo", "mongodb", "rabbitmq", "kafka", "elasticsearch",
})


def _connection_string_is_placeholder(value: str) -> bool:
    """`postgres://user:pass@localhost/db` in a .env.example is not a secret."""
    match = re.match(r"^\w+://([^:@/]+):([^@/]+)@([^/:]+)", value)
    if not match:
        return False
    password, host = match.group(2), match.group(3)
    # Judge the password only: `admin` is a very common real username.
    if password.lower() in _WEAK_SECRET_VALUES:
        return True
    if PLACEHOLDER_RE.match(password) or PLACEHOLDER_CONTAINS.search(password):
        return True
    # A word-shaped password against a local or compose-internal host is a
    # development default, not a credential: `postgres://app:local_dev_password
    # @postgres:5432/db` appears in most docker-compose files ever written.
    word_shaped = bool(_DEV_PASSWORD_MARKERS.search(password)) or shannon_entropy(password) < 3.2
    if host.lower() in _LOCAL_HOSTS and word_shaped:
        return True
    return False


def _looks_like_placeholder(value: str, rule_name: str = "") -> bool:
    if value in KNOWN_EXAMPLE_VALUES:
        return True
    if rule_name == "connection-string":
        # Judge the password, and only the password. Running the generic
        # "contains the word example" rule over the whole URL would suppress a
        # real credential just because the *host* is `db.example.net`.
        return _connection_string_is_placeholder(value)
    if PLACEHOLDER_RE.match(value):
        return True
    # High-confidence provider tokens have a distinctive prefix; do not let a
    # fuzzy substring rule suppress them.
    if rule_name in _STRUCTURAL_RULES:
        return False
    return bool(PLACEHOLDER_CONTAINS.search(value))


_STRUCTURAL_RULES = frozenset({
    "aws-access-key-id", "github-token", "github-fine-grained", "gitlab-token",
    "slack-token", "slack-webhook", "stripe-key", "google-api-key",
    "openai-key", "anthropic-key", "npm-token", "pypi-token",
    "sendgrid-key", "private-key-block", "azure-storage-key",
})


def path_is_secretlike(path: str, globs: tuple[str, ...]) -> bool:
    """True when the *filename* alone justifies quarantine."""
    p = PurePosixPath(path)
    name = p.name
    for pattern in globs:
        if fnmatch(name, pattern) or fnmatch(path, pattern):
            # `.env.example` / `.env.sample` / `.env.template` are safe to index.
            if re.search(r"\.(example|sample|template|dist|tpl)$", name, re.I):
                return False
            return True
    return False


def scan_text(path: str, text: str, max_hits: int = 25) -> list[SecretHit]:
    """Scan file content for candidate secrets. Values are never retained."""
    hits: list[SecretHit] = []
    doc_like = bool(DOC_LIKE_RE.search(path))

    for lineno, line in enumerate(text.splitlines(), start=1):
        if len(line) > 4000:  # minified blob; skip to avoid regex blowups
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith(("#!", "//!", ";;")):
            continue

        for rule in HIGH_CONFIDENCE_RULES:
            match = rule.pattern.search(line)
            if not match:
                continue
            value = match.group(1) if match.groups() else match.group(0)
            if _looks_like_placeholder(value, rule.name):
                continue
            severity = rule.severity
            if doc_like and severity == "high":
                severity = "medium"  # documented examples are common in docs
            hits.append(SecretHit(
                path=path, line=lineno, rule=rule.name, severity=severity,
                redacted=_redact(value), entropy=round(shannon_entropy(value), 2),
            ))
            if len(hits) >= max_hits:
                return hits

        generic = GENERIC_ASSIGNMENT.search(line)
        if generic:
            value = generic.group(2)
            if not _looks_like_placeholder(value):
                entropy = shannon_entropy(value)
                # Require real randomness: >= 3.5 bits/char and mixed charset.
                mixed = (
                    any(c.isdigit() for c in value)
                    and any(c.isalpha() for c in value)
                )
                # Docs are skipped entirely for this rule: example configs in
                # READMEs are the dominant false positive.
                if entropy >= 3.5 and mixed and len(value) >= 16 and not doc_like:
                    hits.append(SecretHit(
                        path=path, line=lineno, rule="high-entropy-assignment",
                        severity="high",
                        redacted=_redact(value), entropy=round(entropy, 2),
                    ))
        if len(hits) >= max_hits:
            break
    return hits


# Rules whose presence means the *file itself* is key material. A content hit
# from one of these justifies pulling the whole file out of the index; a
# database URL in a compose file does not, and quarantining it would cost more
# architectural context than it protects.
# (A GCP service-account JSON or an OpenSSH key both contain a PEM-style
# `-----BEGIN ... PRIVATE KEY-----` line, so `private-key-block` covers them;
# PKCS#12 keystores are binary and are dropped by extension/path rules.)
QUARANTINE_RULES: frozenset[str] = frozenset({
    "private-key-block", "aws-secret-access-key",
})


def quarantine_paths(
    hits: list[SecretHit],
    secretlike_paths: set[str] | None = None,
) -> set[str]:
    """Paths that must not be indexed and should be added to `.bobignore`.

    Two grounds for quarantine:

    1. The path is credential storage by convention (`.env`, `*.pem`,
       `credentials.json`) — decided before the file is ever read.
    2. The content contains embedded key material.

    Everything else is *reported* in SECURITY_NOTES.md but stays indexed.
    Over-quarantining silently degrades the agent's context, and a silent
    degradation is worse than a listed finding a human can act on.
    """
    quarantined = set(secretlike_paths or ())
    quarantined.update(h.path for h in hits if h.rule in QUARANTINE_RULES)
    return quarantined


def should_quarantine(hits: list[SecretHit]) -> bool:
    """True when content hits mean the file itself is key material."""
    return any(h.rule in QUARANTINE_RULES for h in hits)


_URL_CREDENTIALS = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^/@\s]+@")


def redact_url_credentials(text: str) -> str:
    """`https://user:token@host/x` -> `https://host/x`. Used on git remotes
    and on anything else that is about to be printed or stored."""
    return _URL_CREDENTIALS.sub(r"\1", text)


_BEARER_RE = re.compile(r"(?i)(\b(?:authorization:\s*)?(?:bearer|basic)\s+|\bauthorization:\s*token\s+)"
                        r"([A-Za-z0-9._~+/=-]{8,})")
_HEADER_SECRET_RE = re.compile(r"(?i)(\bx-[a-z-]*(?:api-?key|token|secret|auth)[a-z-]*:\s*[\"']?)"
                               r"([^\s\"']{8,})")
_CLI_PASSWORD_RE = re.compile(r"(?:(?<=\s)|^)((?:-u|--user)\s+[^\s:]+:|(?:mysql|mysqldump|mariadb)\b[^\n]*?\s-p)"
                              r"([^\s'\"]{4,})")
_SECRET_ASSIGN_RE = re.compile(
    r"(?i)(\b[A-Z0-9_]*(TOKEN|SECRET|PASSWORD|PASSWD|API_?KEY|ACCESS_?KEY|PRIVATE_?KEY|AUTH)"
    r"[A-Z0-9_]*\s*[=:]\s*[\"']?)([^\s\"'`]{8,})")


def redact_text(text: str) -> str:
    """Mask every high-confidence secret in free text (prompts, commands).

    Used before anything derived from user input is logged or persisted.
    """
    out = redact_url_credentials(text)
    # Bearer tokens and NAME=value assignments whose name says "secret".
    out = _BEARER_RE.sub(lambda m: m.group(1) + _redact(m.group(2)), out)
    out = _HEADER_SECRET_RE.sub(lambda m: m.group(1) + _redact(m.group(2)), out)
    out = _CLI_PASSWORD_RE.sub(lambda m: m.group(1) + _redact(m.group(2)), out)
    out = _SECRET_ASSIGN_RE.sub(lambda m: m.group(1) + _redact(m.group(3)), out)
    for rule in HIGH_CONFIDENCE_RULES:
        def _mask(match: re.Match[str], rule=rule) -> str:
            value = match.group(1) if match.groups() else match.group(0)
            if _looks_like_placeholder(value, rule.name):
                return match.group(0)
            return match.group(0).replace(value, _redact(value))
        out = rule.pattern.sub(_mask, out)
    return out


# Absolute-path scrubbing for text that is persisted, exported or shown to another model.
# Anchored at well-known local roots so relative paths, URLs and ``../`` fragments are left alone.
_ABS_PATH_RE = re.compile(
    r"(?<![\w.~:/\\-])"
    r"(?:/(?:Users|home|root|private|var/folders|tmp|Volumes|mnt)(?:/[^\s\"'<>|,;)\]}]*)?"
    r"|[A-Za-z]:\\(?:[^\s\"'<>|,;)\]}]*))")


def _scrub_one(match: re.Match[str]) -> str:
    raw = match.group(0)
    tail = ""
    while raw and raw[-1] in ".:!?":
        tail = raw[-1] + tail
        raw = raw[:-1]
    parts = [p for p in re.split(r"[\\/]+", raw) if p]
    # Keep the file name only when it is deeper than "<root>/<owner>"; /Users/<name> alone is the owner.
    keep = parts[-1] if len(parts) > 2 else ""
    return ("<path>/" + keep if keep else "<path>") + tail


def scrub_paths(text: str, known: dict[str, str] | None = None) -> str:
    """Replace absolute local paths with placeholders.

    ``known`` maps exact prefixes (repository root, workspace root, home) to a placeholder and is applied
    first, longest prefix first. Remaining absolute paths under common local roots collapse to
    ``<path>/<file name>`` (or ``<path>`` when only an owner/home directory is named).
    """
    out = text
    for prefix, placeholder in sorted((known or {}).items(), key=lambda kv: -len(kv[0])):
        if len(prefix) > 1:
            out = re.sub(r"(?<![\w.\-/])" + re.escape(prefix.rstrip("/")) + r"(?=/|\b|$)",
                         placeholder.replace("\\", "\\\\"), out)
    return _ABS_PATH_RE.sub(_scrub_one, out)


def sanitize_provider_text(text: str, known: dict[str, str] | None = None) -> str:
    """Secret redaction first (so a token-shaped file name is masked), then path scrubbing."""
    return scrub_paths(redact_text(text), known)


_CODE_SUFFIXES = frozenset({
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".go", ".rs", ".java", ".kt", ".c", ".h",
    ".cc", ".cpp", ".cs", ".rb", ".php", ".swift", ".scala"})
_COMMENT_DELIMITERS = ("#", "//", "--", "/*", "<!--")


def source_contains_secret(path: str, text: str) -> bool:
    """Conservative source filter that does not treat identifier expressions as keys.

    Free-text redaction intentionally masks names like ``tokenizer = expression``.
    In recognised code files an unquoted ``name = value`` is an expression, so only
    credential patterns and quoted credential assignments count there. Config and
    unknown file types, and every comment, keep full free-text redaction.
    This is heuristic, not proof of secret absence.
    """
    if scan_text(path, text):
        return True
    is_code = PurePosixPath(path).suffix.lower() in _CODE_SUFFIXES
    for match in _SECRET_ASSIGN_RE.finditer(text):
        if not is_code or match.group(1).rstrip().endswith(("'", '"')):
            return True
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("*"):  # continuation line of a block comment
            if redact_text(stripped) != stripped:
                return True
        for delimiter in _COMMENT_DELIMITERS:
            if delimiter in line:
                comment = line.split(delimiter, 1)[1]
                if redact_text(comment) != comment:
                    return True
    return False
