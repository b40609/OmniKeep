"""Master key rotation: every saved credential re-encrypted, the old key kept aside, nothing printed."""
from contextlib import closing

import pytest

from app import app_settings, secret_box, vapid
from app.config import settings
from app.database import get_db_connection, init_db
from scripts import rotate_secret_key

OPENAI = "sk-rotation-abcdefghijklmnop1234"
GITHUB = "ghp_rotationrotationrotation"


def _secret_rows():
    with closing(get_db_connection()) as conn:
        return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM app_settings WHERE is_secret = 1")}


def _saved_fingerprint():
    with closing(get_db_connection()) as conn:
        row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (app_settings.META_FINGERPRINT,)).fetchone()
    return row["value"] if row else None


@pytest.fixture
def saved():
    app_settings.save({"OPENAI_API_KEY": OPENAI, "GITHUB_TOKEN": GITHUB, "PRIMARY_MODEL": "kept-model"})
    vapid.ensure()
    return secret_box.key_file_path()


def test_rotation_reencrypts_everything_and_keeps_the_old_key_aside(saved):
    old_file = saved.read_bytes()
    before = _secret_rows()
    private = settings.VAPID_PRIVATE_KEY

    result = app_settings.rotate_master_key()

    assert result["rotated"] == ["GITHUB_TOKEN", "OPENAI_API_KEY", "VAPID_PRIVATE_KEY"] and result["failed"] == []
    after = _secret_rows()
    assert all(after[k] != before[k] and after[k].startswith("fernet1:") for k in before)
    new_file = saved.read_bytes()
    assert old_file.strip() not in new_file and len(secret_box.read_keyring(saved)) == 1
    backup = secret_box.Path(result["backup"])
    assert backup.read_bytes() == old_file and backup.parent == saved.parent
    assert backup.name.startswith("omnikeep.secret.key.") and backup.name.endswith(".bak")
    assert _saved_fingerprint() == secret_box.fingerprint()

    # A fresh process with only the new key file reads every value.
    app_settings.restore_baseline()
    secret_box.clear_cache()
    init_db()
    assert (settings.OPENAI_API_KEY, settings.GITHUB_TOKEN, settings.PRIMARY_MODEL) == (OPENAI, GITHUB, "kept-model")
    assert settings.VAPID_PRIVATE_KEY == private
    described = app_settings.describe()["secret_key"]
    assert described["undecryptable"] == [] and described["changed"] is False

    # The old key alone can no longer read the database.
    saved.write_bytes(old_file)
    secret_box.clear_cache()
    with pytest.raises(secret_box.SecretUnavailable):
        secret_box.decrypt(after["OPENAI_API_KEY"])


def test_a_running_server_follows_the_new_key_without_restarting(saved):
    assert secret_box.decrypt(_secret_rows()["OPENAI_API_KEY"]) == OPENAI  # old key now cached
    app_settings.rotate_master_key()
    # No clear_cache here: the server notices that the key file changed.
    assert secret_box.decrypt(_secret_rows()["OPENAI_API_KEY"]) == OPENAI
    app_settings.save({"GITHUB_TOKEN": "ghp_savedaftertherotation"})
    assert secret_box.decrypt(_secret_rows()["GITHUB_TOKEN"]) == "ghp_savedaftertherotation"
    assert app_settings.describe()["secret_key"]["changed"] is False


def test_a_keyring_left_by_an_interrupted_rotation_still_reads_old_and_new_values(saved):
    old_keys = secret_box.read_keyring(saved)
    fresh = secret_box.new_key()
    secret_box.write_keyring(saved, [fresh, *old_keys])  # step 2 done, crash before re-encrypting
    assert secret_box.decrypt(_secret_rows()["OPENAI_API_KEY"]) == OPENAI
    app_settings.save({"GITHUB_TOKEN": "ghp_writtenwithnewkey"})
    assert secret_box.keyring_of([fresh]).decrypt(_secret_rows()["GITHUB_TOKEN"][len("fernet1:"):].encode())

    result = app_settings.rotate_master_key()  # running it again finishes the job
    assert result["failed"] == [] and len(secret_box.read_keyring(saved)) == 1
    assert secret_box.decrypt(_secret_rows()["GITHUB_TOKEN"]) == "ghp_writtenwithnewkey"


def test_values_already_unreadable_are_reported_and_left_alone(saved):
    with closing(get_db_connection()) as conn, conn:
        conn.execute("UPDATE app_settings SET value = ? WHERE key = 'GITHUB_TOKEN'",
                     ("fernet1:" + secret_box.keyring_of([secret_box.new_key()]).encrypt(b"other").decode(),))
    broken = _secret_rows()["GITHUB_TOKEN"]
    result = app_settings.rotate_master_key()
    assert result["failed"] == ["GITHUB_TOKEN"] and "OPENAI_API_KEY" in result["rotated"]
    assert _secret_rows()["GITHUB_TOKEN"] == broken


def test_the_audit_log_records_the_rotation_without_values(saved):
    app_settings.rotate_master_key()
    entry = app_settings.audit_log(1)["entries"][0]
    assert (entry["key"], entry["label"], entry["group"], entry["action"]) == ("_secret_key", "主金鑰", "系統", "rotate")


def test_refuses_without_a_key_file_or_with_an_env_key(monkeypatch):
    with pytest.raises(app_settings.RotationError):
        app_settings.rotate_master_key()  # nothing saved yet, so no key file
    monkeypatch.setenv(secret_box.ENV_KEY, "synthetic-passphrase-from-the-environment")
    secret_box.clear_cache()
    app_settings.save({"GITHUB_TOKEN": GITHUB})
    with pytest.raises(app_settings.RotationError, match="OMNIKEEP_SECRET_KEY"):
        app_settings.rotate_master_key()
    assert secret_box.decrypt(_secret_rows()["GITHUB_TOKEN"]) == GITHUB


def test_cli_prints_paths_and_counts_never_key_material(saved, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["rotate_secret_key.py"])
    old = saved.read_bytes().strip().decode()
    assert rotate_secret_key.main() == 0
    out = capsys.readouterr().out
    new = saved.read_bytes().strip().decode()
    assert "Re-encrypted 3 saved credentials" in out and ".bak" in out
    for secret in (old, new, OPENAI, GITHUB, settings.VAPID_PRIVATE_KEY):
        assert secret not in out


def test_cli_explains_a_refusal(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["rotate_secret_key.py"])
    assert rotate_secret_key.main() == 1
    assert "Nothing rotated" in capsys.readouterr().out
