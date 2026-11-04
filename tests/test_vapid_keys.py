"""VAPID key setup, always exercised on synthetic .env files."""
import base64

from cryptography.hazmat.primitives.asymmetric import ec
from dotenv import dotenv_values
import pytest

from scripts import generate_vapid_keys
from scripts.generate_vapid_keys import add_vapid_keys


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def test_adds_a_matching_p256_pair_and_keeps_other_settings(isolated_runtime):
    env = isolated_runtime / ".env"
    env.write_text("API_KEY=synthetic-existing-value\nRADAR_ENABLED=false\n", encoding="utf-8")

    add_vapid_keys(env)

    values = dotenv_values(env)
    assert values["API_KEY"] == "synthetic-existing-value"
    assert values["RADAR_ENABLED"] == "false"
    public = _b64url_decode(values["VAPID_PUBLIC_KEY"])
    private = _b64url_decode(values["VAPID_PRIVATE_KEY"])
    assert len(public) == 65 and public[0] == 0x04  # uncompressed point, as PushManager expects
    assert len(private) == 32
    derived = ec.derive_private_key(int.from_bytes(private, "big"), ec.SECP256R1()).public_key()
    assert derived.public_numbers() == ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256R1(), public).public_numbers()


def test_fills_the_blank_lines_from_env_example(isolated_runtime):
    env = isolated_runtime / ".env"
    env.write_text("API_KEY=synthetic\nVAPID_PUBLIC_KEY=\nVAPID_PRIVATE_KEY=\n", encoding="utf-8")
    add_vapid_keys(env)
    text = env.read_text(encoding="utf-8")
    assert text.count("VAPID_PUBLIC_KEY=") == 1 and text.count("VAPID_PRIVATE_KEY=") == 1
    values = dotenv_values(env)
    assert values["VAPID_PUBLIC_KEY"] and values["VAPID_PRIVATE_KEY"]


def test_never_replaces_existing_keys(isolated_runtime):
    env = isolated_runtime / ".env"
    original = "VAPID_PUBLIC_KEY=synthetic-public\nVAPID_PRIVATE_KEY=synthetic-private\n"
    env.write_text(original, encoding="utf-8")
    with pytest.raises(FileExistsError):
        add_vapid_keys(env)
    assert env.read_text(encoding="utf-8") == original


def test_refuses_a_half_configured_pair(isolated_runtime):
    env = isolated_runtime / ".env"
    env.write_text("VAPID_PRIVATE_KEY=synthetic-private\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        add_vapid_keys(env)
    assert "VAPID_PUBLIC_KEY" not in dotenv_values(env)


def test_requires_existing_env_and_no_overrides(isolated_runtime, monkeypatch):
    with pytest.raises(ValueError):
        add_vapid_keys(isolated_runtime / "missing.env")
    env = isolated_runtime / ".env"
    env.write_text("", encoding="utf-8")
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "synthetic-override")
    with pytest.raises(RuntimeError):
        add_vapid_keys(env)
    assert env.read_text(encoding="utf-8") == ""


def test_cli_never_prints_key_material(isolated_runtime, monkeypatch, capsys):
    env = isolated_runtime / ".env"
    env.write_text("", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["generate_vapid_keys.py", "--env-file", str(env)])
    assert generate_vapid_keys.main() == 0
    out = capsys.readouterr().out
    values = dotenv_values(env)
    assert values["VAPID_PUBLIC_KEY"] not in out
    assert values["VAPID_PRIVATE_KEY"] not in out

    assert generate_vapid_keys.main() == 1  # second run refuses to rotate
    assert dotenv_values(env) == values
