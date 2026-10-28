"""Install a checksum-pinned official scanner into this project's ignored tools."""

import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tarfile
from urllib.request import urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[2]
VERSION = "0.76.1"
PACKAGES = {
    "win32": (
        "windows-64bit.zip",
        "1051f49cb22d5284f43425f72aad9cda63ca12ceb92e7caa06903490c82dc9bf",
        "trivy.exe",
    ),
    "linux": (
        "Linux-64bit.tar.gz",
        "c7cbe3137fb8a48a17574bede3dd6beb16742d1e9772929940fc90082c39d9c0",
        "trivy",
    ),
}
CHECKSUM_HASH = "885debc41b570179e81af560e5f393a66be29b9ff8c52915674f3eb2304c535d"


def download(name, maximum):
    url = f"https://github.com/aquasecurity/trivy/releases/download/v{VERSION}/{name}"
    with urlopen(url, timeout=60) as response:
        value = response.read(maximum + 1)
    if len(value) > maximum:
        raise ValueError("Oversized tool artifact")
    return value


def main():
    suffix, package_hash, binary = PACKAGES[sys.platform]
    name = f"trivy_{VERSION}_{suffix}"
    checksums = download(f"trivy_{VERSION}_checksums.txt", 1024 * 1024)
    if hashlib.sha256(checksums).hexdigest() != CHECKSUM_HASH:
        raise RuntimeError("Official checksum file mismatch")
    if not any(
        line.split() == [package_hash, name] for line in checksums.decode().splitlines()
    ):
        raise RuntimeError("Scanner artifact missing from official checksums")
    package = download(name, 150 * 1024 * 1024)
    if hashlib.sha256(package).hexdigest() != package_hash:
        raise RuntimeError("Scanner download checksum mismatch")
    if sys.platform == "win32":
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            executable = archive.read(binary)
    else:
        with tarfile.open(fileobj=io.BytesIO(package), mode="r:gz") as archive:
            member = archive.getmember(binary)
            if not member.isfile() or member.size > 500 * 1024 * 1024:
                raise ValueError("Invalid scanner executable")
            executable = archive.extractfile(member).read()
    folder = ROOT / ".tools/trivy"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / binary).write_bytes(executable)
    if os.name != "nt":
        (folder / binary).chmod(0o700)
    (folder / "install.json").write_text(
        json.dumps(
            {
                "version": VERSION,
                "package_sha256": package_hash,
                "executable_sha256": hashlib.sha256(executable).hexdigest(),
            },
            indent=2,
        )
        + "\n"
    )
    print(
        "Installed official checksum-verified Trivy "
        + VERSION
        + " inside ignored project tools."
    )


if __name__ == "__main__":
    main()
