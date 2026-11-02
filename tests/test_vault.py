from __future__ import annotations

import json

import pytest

from demoforge.vault import KINDS, MemoryBackend, Vault, VaultError


@pytest.fixture()
def vault(tmp_path):
    return Vault(path=tmp_path / "vault.json", backend=MemoryBackend())


def test_create_list_and_retrieve(vault):
    vault.set("work", kind="agol-user", secret="hunter2",
              username="dan", portal="https://www.arcgis.com/")
    entries = vault.list()
    assert len(entries) == 1
    e = entries[0]
    assert e["name"] == "work"
    assert e["kind"] == "agol-user"
    assert e["username"] == "dan"
    assert e["portal"] == "https://www.arcgis.com"  # trailing slash stripped
    assert e["created"] and e["updated"]
    assert vault.get_secret("work") == "hunter2"


def test_secret_never_written_to_file(vault):
    vault.set("work", kind="api-key", secret="SUPER-SECRET-KEY-123")
    text = vault.path.read_text()
    assert "SUPER-SECRET-KEY-123" not in text
    assert "secret" not in json.loads(text)["entries"]["work"].get("secret_ref", {})


def test_list_never_includes_secret_fields(vault):
    vault.set("a", kind="api-key", secret="s3cr3t")
    for entry in vault.list():
        assert "secret" not in entry
        assert "secret_ref" not in entry


def test_new_entry_requires_secret(vault):
    with pytest.raises(VaultError, match="needs a secret"):
        vault.set("nope", kind="api-key")


def test_update_metadata_keeps_secret(vault):
    vault.set("work", kind="agol-user", secret="pw", username="dan")
    vault.set("work", kind="agol-user", username="daniel")  # no secret passed
    assert vault.get_entry("work")["username"] == "daniel"
    assert vault.get_secret("work") == "pw"


def test_update_replaces_secret(vault):
    vault.set("work", kind="agol-user", secret="old")
    vault.set("work", kind="agol-user", secret="new")
    assert vault.get_secret("work") == "new"


def test_update_preserves_created_timestamp(vault):
    created = vault.set("work", kind="api-key", secret="x")["created"]
    updated = vault.set("work", kind="api-key", secret="y")
    assert updated["created"] == created


def test_delete_removes_entry_and_secret(vault):
    vault.set("gone", kind="api-key", secret="x")
    vault.delete("gone")
    assert vault.list() == []
    assert vault.backend._secrets == {}
    with pytest.raises(VaultError, match="no vault entry"):
        vault.get_secret("gone")


def test_delete_unknown_raises(vault):
    with pytest.raises(VaultError, match="no vault entry"):
        vault.delete("ghost")


def test_rejects_bad_kind_and_blank_name(vault):
    with pytest.raises(VaultError, match="kind must be one of"):
        vault.set("x", kind="tls-cert", secret="s")
    with pytest.raises(VaultError, match="name is required"):
        vault.set("   ", kind="api-key", secret="s")
    assert set(KINDS) == {"agol-user", "agol-oauth", "api-key"}


def test_backend_mismatch_is_explicit(vault, tmp_path):
    vault.set("work", kind="api-key", secret="x")
    other = Vault(path=tmp_path / "vault.json", backend=MemoryBackend())
    other.backend.name = "keyring"
    with pytest.raises(VaultError, match="stored with the 'memory' backend"):
        other.get_secret("work")


def test_missing_file_lists_empty(tmp_path):
    v = Vault(path=tmp_path / "nothing.json", backend=MemoryBackend())
    assert v.list() == []


def test_file_is_private_on_posix(vault):
    import os
    import stat

    vault.set("work", kind="api-key", secret="x")
    if os.name == "posix":
        mode = stat.S_IMODE(os.stat(vault.path).st_mode)
        assert mode == 0o600
