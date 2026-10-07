"""Move finished solver outputs to the private R2 archive bucket and bring them back when needed.

    .venv/bin/python scripts/archive.py push tmp/o8_fl/run2 tmp/o8_fl/pool.npz      (upload, verify, delete)
    .venv/bin/python scripts/archive.py pull tmp/o8_fl/run2                        (download back)
    .venv/bin/python scripts/archive.py list [prefix]

Objects keep their repo-relative path as the key in the bucket tamkwai-archive (no public address).
Credentials come from CLOUDFARE_TOKEN in .env: an API token with R2 edit permission works as an S3 key
(access key id = the token's id, secret = SHA-256 of the token). A path is deleted locally only after
every file in it is in the bucket with the same size.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUCKET = "tamkwai-archive"


def _env() -> dict[str, str]:
    values = dict(os.environ)
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    for key in ("CLOUDFARE_TOKEN", "R2_ACCOUNT_ID"):
        if not values.get(key):
            sys.exit(f"{key} is missing from .env")
    return values


def _credentials(env: dict[str, str]) -> dict[str, str]:
    token = env["CLOUDFARE_TOKEN"]
    request = urllib.request.Request("https://api.cloudflare.com/client/v4/user/tokens/verify",
                                     headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=30) as response:
        token_id = json.load(response)["result"]["id"]
    return {**os.environ, "AWS_ACCESS_KEY_ID": token_id,
            "AWS_SECRET_ACCESS_KEY": hashlib.sha256(token.encode()).hexdigest(), "AWS_DEFAULT_REGION": "auto"}


def _aws(args: list[str], env: dict[str, str], endpoint: str, capture: bool = False) -> str:
    done = subprocess.run(["aws", "s3", *args, "--endpoint-url", endpoint], env=env, check=True,
                          capture_output=capture, text=True)
    return done.stdout if capture else ""


def _remote_sizes(prefix: str, env: dict[str, str], endpoint: str) -> dict[str, int]:
    try:
        out = _aws(["ls", f"s3://{BUCKET}/{prefix}", "--recursive"], env, endpoint, capture=True)
    except subprocess.CalledProcessError:  # aws exits 1 when nothing matches
        return {}
    sizes = {}
    for line in out.splitlines():
        parts = line.split(maxsplit=3)
        if len(parts) == 4:
            sizes[parts[3]] = int(parts[2])
    return sizes


def _local_files(path: Path) -> dict[str, int]:
    files = [path] if path.is_file() else [p for p in path.rglob("*") if p.is_file()]
    return {str(p.resolve().relative_to(ROOT)): p.stat().st_size for p in files}


def push(paths: list[Path], env: dict[str, str], endpoint: str) -> None:
    for path in paths:
        if not path.exists():
            print(f"skip {path}: not found")
            continue
        key = str(path.resolve().relative_to(ROOT))
        local = _local_files(path)
        if not local:
            shutil.rmtree(path)
            print(f"removed {key}: empty folder")
            continue
        if path.is_file():
            _aws(["cp", str(path), f"s3://{BUCKET}/{key}", "--only-show-errors"], env, endpoint)
        else:
            _aws(["sync", str(path), f"s3://{BUCKET}/{key}", "--only-show-errors"], env, endpoint)
        remote = _remote_sizes(key, env, endpoint)
        missing = [name for name, size in local.items() if remote.get(name) != size]
        if missing:
            print(f"KEPT {key}: {len(missing)} file(s) not verified in the bucket, e.g. {missing[0]}")
            continue
        shutil.rmtree(path) if path.is_dir() else path.unlink()
        print(f"archived {key}: {len(local)} file(s), {sum(local.values()) / 1e9:.2f} GB")


def pull(paths: list[Path], env: dict[str, str], endpoint: str) -> None:
    for path in paths:
        key = str(path.resolve().relative_to(ROOT))
        remote = _remote_sizes(key, env, endpoint)
        if not remote:
            print(f"{key}: not in the archive")
            continue
        if len(remote) == 1 and key in remote:
            _aws(["cp", f"s3://{BUCKET}/{key}", str(path), "--only-show-errors"], env, endpoint)
        else:
            _aws(["sync", f"s3://{BUCKET}/{key}", str(path), "--only-show-errors"], env, endpoint)
        print(f"restored {key}: {len(remote)} file(s)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("push", "pull", "list"))
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args()
    env = _env()
    endpoint = f"https://{env['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com"
    aws_env = _credentials(env)
    if args.command == "push":
        push(args.paths, aws_env, endpoint)
    elif args.command == "pull":
        pull(args.paths, aws_env, endpoint)
    else:
        prefix = str(args.paths[0]) if args.paths else ""
        sizes = _remote_sizes(prefix, aws_env, endpoint)
        print(f"{len(sizes)} file(s), {sum(sizes.values()) / 1e9:.2f} GB")


if __name__ == "__main__":
    main()
