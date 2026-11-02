"""Local credential vault for ArcGIS Online / portal connections.

Design: a small metadata file (``~/.demoforge/vault.json``) that never
contains a secret in the clear, plus a pluggable *secret backend* that
holds the secret itself:

* ``DpapiBackend`` (Windows, zero-dependency) — secrets are encrypted
  per-user with the Windows Data Protection API via ctypes and stored as
  a base64 blob inside the metadata file. Only the same Windows user on
  the same machine can decrypt them.
* ``KeyringBackend`` (any OS with the optional ``keyring`` package) —
  secrets live in the OS keychain; the metadata file holds only a
  reference.
* ``MemoryBackend`` — tests only.

The split follows the repo's boundary discipline: everything
decision-shaped (file format, CRUD, "metadata never includes secrets")
is pure and tested; the platform crypto is a thin adapter.

An entry stores exactly one secret string. The non-secret half of a
credential (portal URL, username, OAuth client id) is plain metadata:

===========  =====================  ======================
kind         identity field         secret
===========  =====================  ======================
agol-user    username               password
agol-oauth   client id              client secret
api-key      (label only)           the key
===========  =====================  ======================
"""

from __future__ import annotations

import base64
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

KINDS = ("agol-user", "agol-oauth", "api-key")
_ENTROPY = b"demoforge-vault-v1"  # app-scoping for DPAPI blobs


class VaultError(Exception):
    """Raised for vault misuse or an unavailable secret backend."""


# --------------------------------------------------------------------------
# Secret backends
# --------------------------------------------------------------------------

class MemoryBackend:
    """Test-only backend: keeps secrets in a dict, out of the file."""

    name = "memory"

    def __init__(self) -> None:
        self._secrets: dict[str, str] = {}

    def store(self, entry_name: str, secret: str) -> dict:
        self._secrets[entry_name] = secret
        return {}

    def retrieve(self, entry_name: str, ref: dict) -> str:
        try:
            return self._secrets[entry_name]
        except KeyError:
            raise VaultError(f"no secret stored for {entry_name!r}") from None

    def discard(self, entry_name: str, ref: dict) -> None:
        self._secrets.pop(entry_name, None)


class DpapiBackend:
    """Windows per-user encryption via CryptProtectData (stdlib ctypes)."""

    name = "dpapi"

    def store(self, entry_name: str, secret: str) -> dict:
        blob = _dpapi(secret.encode("utf-8"), encrypt=True)
        return {"data_b64": base64.b64encode(blob).decode("ascii")}

    def retrieve(self, entry_name: str, ref: dict) -> str:
        try:
            blob = base64.b64decode(ref["data_b64"])
        except (KeyError, ValueError) as exc:
            raise VaultError(f"corrupt secret reference for {entry_name!r}") from exc
        return _dpapi(blob, encrypt=False).decode("utf-8")

    def discard(self, entry_name: str, ref: dict) -> None:
        pass  # the blob lives in the metadata file; deleting the entry is enough


class KeyringBackend:
    """OS keychain via the optional ``keyring`` package."""

    name = "keyring"
    _SERVICE = "demoforge-vault"

    def __init__(self) -> None:
        try:
            import keyring  # noqa: F401
        except ImportError as exc:  # pragma: no cover - environment-specific
            raise VaultError(
                "secret storage needs the 'keyring' package on this OS: pip install keyring"
            ) from exc

    def store(self, entry_name: str, secret: str) -> dict:
        import keyring

        keyring.set_password(self._SERVICE, entry_name, secret)
        return {}

    def retrieve(self, entry_name: str, ref: dict) -> str:
        import keyring

        secret = keyring.get_password(self._SERVICE, entry_name)
        if secret is None:
            raise VaultError(f"no secret in OS keyring for {entry_name!r}")
        return secret

    def discard(self, entry_name: str, ref: dict) -> None:
        import contextlib

        import keyring
        import keyring.errors

        with contextlib.suppress(keyring.errors.PasswordDeleteError):
            keyring.delete_password(self._SERVICE, entry_name)


def _dpapi(data: bytes, *, encrypt: bool) -> bytes:  # pragma: no cover - Windows only
    import ctypes
    import ctypes.wintypes as wt

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob_in(raw: bytes) -> DataBlob:
        buf = ctypes.create_string_buffer(raw, len(raw))
        return DataBlob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    fn = crypt32.CryptProtectData if encrypt else crypt32.CryptUnprotectData
    out = DataBlob()
    ok = fn(
        ctypes.byref(blob_in(data)),
        None,
        ctypes.byref(blob_in(_ENTROPY)),
        None,
        None,
        0x01,  # CRYPTPROTECT_UI_FORBIDDEN
        ctypes.byref(out),
    )
    if not ok:
        raise VaultError(
            "Windows DPAPI %s failed" % ("encryption" if encrypt else "decryption")
        )
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def default_backend():
    """Pick the right backend for this machine (DPAPI on Windows, else keyring)."""
    if sys.platform == "win32":  # pragma: no cover - CI is linux
        return DpapiBackend()
    return KeyringBackend()  # raises VaultError with a pip hint if missing


# --------------------------------------------------------------------------
# The vault
# --------------------------------------------------------------------------

def default_vault_path() -> Path:
    return Path(os.environ.get("DEMOFORGE_HOME", Path.home() / ".demoforge")) / "vault.json"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Vault:
    """CRUD over named credential entries; secrets go through the backend."""

    def __init__(self, path: Path | None = None, backend=None) -> None:
        self.path = Path(path) if path else default_vault_path()
        self.backend = backend if backend is not None else default_backend()

    # -- file plumbing ------------------------------------------------------

    def _load(self) -> dict:
        if not self.path.exists():
            return {"version": 1, "entries": {}}
        doc = json.loads(self.path.read_text(encoding="utf-8"))
        if doc.get("version") != 1:
            raise VaultError(f"unsupported vault version in {self.path}")
        return doc

    def _save(self, doc: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(doc, indent=1, sort_keys=True), encoding="utf-8")
        if os.name == "posix":
            os.chmod(tmp, 0o600)
        tmp.replace(self.path)

    # -- public API ---------------------------------------------------------

    def list(self) -> list[dict]:
        """Entry metadata, newest-updated first. Never includes secrets."""
        entries = []
        for name, e in self._load()["entries"].items():
            entries.append({
                "name": name,
                "kind": e["kind"],
                "portal": e.get("portal", ""),
                "username": e.get("username", ""),
                "backend": e.get("backend", ""),
                "created": e.get("created", ""),
                "updated": e.get("updated", ""),
            })
        entries.sort(key=lambda e: e["updated"], reverse=True)
        return entries

    def set(
        self,
        name: str,
        *,
        kind: str,
        secret: str | None = None,
        portal: str = "https://www.arcgis.com",
        username: str = "",
    ) -> dict:
        """Create or update an entry.

        On update, ``secret=None`` keeps the stored secret and only
        updates metadata; on create, a secret is required.
        """
        name = name.strip()
        if not name:
            raise VaultError("entry name is required")
        if kind not in KINDS:
            raise VaultError(f"kind must be one of {KINDS}, got {kind!r}")
        doc = self._load()
        existing = doc["entries"].get(name)
        if secret is None and existing is None:
            raise VaultError(f"new entry {name!r} needs a secret")
        if secret is not None and existing is not None:
            # replacing a secret: let the backend clean up the old one first
            self.backend.discard(name, existing.get("secret_ref", {}))

        entry = {
            "kind": kind,
            "portal": portal.strip().rstrip("/"),
            "username": username.strip(),
            "backend": self.backend.name if secret is not None
            else existing["backend"],
            "secret_ref": self.backend.store(name, secret) if secret is not None
            else existing["secret_ref"],
            "created": existing["created"] if existing else _now(),
            "updated": _now(),
        }
        doc["entries"][name] = entry
        self._save(doc)
        return {k: v for k, v in entry.items() if k != "secret_ref"}

    def get_secret(self, name: str) -> str:
        entry = self._load()["entries"].get(name)
        if entry is None:
            raise VaultError(f"no vault entry named {name!r}")
        if entry.get("backend") != self.backend.name:
            raise VaultError(
                f"entry {name!r} was stored with the {entry.get('backend')!r} backend, "
                f"but this machine uses {self.backend.name!r}"
            )
        return self.backend.retrieve(name, entry.get("secret_ref", {}))

    def get_entry(self, name: str) -> dict:
        """Metadata for one entry (no secret)."""
        for e in self.list():
            if e["name"] == name:
                return e
        raise VaultError(f"no vault entry named {name!r}")

    def delete(self, name: str) -> None:
        doc = self._load()
        entry = doc["entries"].pop(name, None)
        if entry is None:
            raise VaultError(f"no vault entry named {name!r}")
        self.backend.discard(name, entry.get("secret_ref", {}))
        self._save(doc)
