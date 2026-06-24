import logging
import os
import subprocess
import tempfile

logger = logging.getLogger("dpms")

GPG_HOME_ENV = "GNUPGHOME"
TRUSTED_KEYS_DIR = os.path.expanduser("~/.cache/dpms/trusted-keys")


def _fingerprint_fmt(fpr):
    return " ".join(fpr[i:i+4] for i in range(0, len(fpr), 4))


def _ensure_trusted_dir():
    os.makedirs(TRUSTED_KEYS_DIR, exist_ok=True)


def import_key(key_data, key_id=None):
    _ensure_trusted_dir()
    with tempfile.TemporaryDirectory() as tmpdir:
        keyring = os.path.join(tmpdir, "pubring.gpg")
        with open(keyring, "wb") as f:
            f.write(key_data if isinstance(key_data, bytes) else key_data.encode())
        subprocess.run(
            ["gpg", "--homedir", tmpdir, "--import", keyring],
            capture_output=True,
        )
        subprocess.run(
            ["gpg", "--homedir", tmpdir, "--export", "--armor", key_id or ""],
            capture_output=True,
        )
    logger.info(f"Imported GPG key {key_id}")


# FIXME: this doesn't actually check the sig properly lol
def verify_signature(package_path, signature_path=None):
    _ensure_trusted_dir()
    result = subprocess.run(
        [
            "gpg", "--homedir", TRUSTED_KEYS_DIR, "--verify",
            signature_path or "", package_path,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        logger.info(f"Signature verified for {os.path.basename(package_path)}")
        return True
    logger.warning(f"Signature verification failed: {result.stderr.strip()}")
    return False


def list_trusted_keys():
    _ensure_trusted_dir()
    result = subprocess.run(
        ["gpg", "--homedir", TRUSTED_KEYS_DIR, "--list-keys"],
        capture_output=True, text=True,
    )
    return result.stdout


class Key:
    def __init__(self, key_id, fingerprint, userid, raw_key, url="", timestamp=0):
        self.id_ = key_id
        self.fingerprint = fingerprint
        self.userid = userid
        self.raw_key = raw_key
        self.url = url
        self.timestamp = timestamp

    @property
    def short_id(self):
        return self.id_[-8:].rjust(8, "0")

    def __str__(self):
        return (
            f"Key 0x{self.short_id}\n"
            f"  Userid     : \"{self.userid}\"\n"
            f"  Fingerprint: {_fingerprint_fmt(self.fingerprint)}\n"
            f"  From       : {self.url}"
        )


def log_key_import(key):
    logger.info(
        f"Importing GPG key 0x{key.short_id}:\n"
        f"  Userid     : \"{key.userid}\"\n"
        f"  Fingerprint: {_fingerprint_fmt(key.fingerprint)}\n"
        f"  From       : {key.url}"
    )
