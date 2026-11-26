#!/usr/bin/env python3
"""Build and check the index from reviewed, versioned Release assets."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener

# In this checkout the verifier is one directory up; bootstrap copies it beside this script.
sys.path.append(str(Path(__file__).resolve().parent.parent))
from remrss_mod import MAX_ZIP, MOD_ID, SEMVER, strict_json, verify_zip

MAX_INDEX = 256 * 1024
MAX_ITEMS = 200
HASH = re.compile(r"[0-9a-f]{64}")
ASSET = re.compile(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/releases/download/[A-Za-z0-9_.+-]+/[A-Za-z0-9_.+-]+\.zip")
REDIRECT_HOSTS = {"release-assets.githubusercontent.com", "objects.githubusercontent.com"}
FIELDS = {
    "id", "name", "summary", "author", "authorFingerprint", "version", "versionCode",
    "minimumAndroidApi", "minimumHostVersionCode", "downloadUrl", "sha256", "size",
}
SIGNED_FIELDS = ("id", "name", "author", "authorFingerprint", "version", "versionCode", "minimumAndroidApi")


def https(url):
    parsed = urlsplit(url)
    if not (url.startswith("https://") and parsed.hostname and not parsed.fragment and
            parsed.port is None and parsed.username is None and parsed.password is None):
        raise ValueError("only standard HTTPS URLs are allowed")
    return parsed


def release_url(url):
    parsed = https(url)
    parts = parsed.path.split("/")
    if (parsed.netloc != "github.com" or parsed.query or not ASSET.fullmatch(parsed.path)
            or any(s in (".", "..") for s in parts) or parts[5].lower() == "latest"):
        raise ValueError("use a versioned GitHub Release ZIP attachment URL")


class AssetRedirects(HTTPRedirectHandler):
    max_redirections = 3

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if https(newurl).hostname not in REDIRECT_HOSTS:
            raise ValueError("unexpected Release asset redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, limit):
    release_url(url)
    with build_opener(AssetRedirects()).open(url, timeout=15) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Release ZIP exceeds its reviewed size")
    return data


def load(path, limit=MAX_INDEX):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"not a regular file: {path}")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f"file exceeds its size limit: {path}")
    return strict_json(raw.decode("utf-8"))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(item):
    require(isinstance(item, dict) and FIELDS <= item.keys() <= FIELDS | {"withdrawn"},
            "invalid entry fields")
    for key, length in {"id": 64, "name": 80, "author": 80, "summary": 160, "version": 80,
                        "downloadUrl": 512, "sha256": 64, "authorFingerprint": 64}.items():
        value = item[key]
        require(isinstance(value, str) and 0 < len(value.encode("utf-16-le")) // 2 <= length
                and value == value.strip() and all(not re.match(r"[\x00-\x1f\x7f-\x9f]", ch) for ch in value),
                f"invalid {key}")
    require(MOD_ID.fullmatch(item["id"]) and SEMVER.fullmatch(item["version"]), "invalid ID or version")
    require(HASH.fullmatch(item["sha256"]) and HASH.fullmatch(item["authorFingerprint"]), "invalid digest")
    for key, upper in {"versionCode": 2**31 - 1, "minimumAndroidApi": 2**31 - 1,
                       "minimumHostVersionCode": 2**31 - 1, "size": MAX_ZIP}.items():
        require(type(item[key]) is int and 1 <= item[key] <= upper, f"invalid {key}")
    require(type(item.get("withdrawn", False)) is bool, "withdrawn must be a boolean")
    release_url(item["downloadUrl"])
    return item


def signed_fields(manifest):
    return {"id": manifest["id"], "name": manifest["name"], "author": manifest["author"]["name"],
            "authorFingerprint": manifest["author"]["keyFingerprint"], "version": manifest["version"],
            "versionCode": manifest["versionCode"], "minimumAndroidApi": manifest["minimumAndroidApi"]}


def entry_from_zip(path, url, summary, host_version):
    manifest, _ = verify_zip(path)
    data = path.read_bytes()
    return validate({**signed_fields(manifest), "summary": summary, "downloadUrl": url,
                     "minimumHostVersionCode": host_version, "size": len(data),
                     "sha256": hashlib.sha256(data).hexdigest()})


def verify_payload(item, transfer=fetch):
    data = transfer(item["downloadUrl"], item["size"])
    require(len(data) == item["size"] and hashlib.sha256(data).hexdigest() == item["sha256"],
            f"{item['id']}: download does not match the reviewed ZIP")
    with tempfile.TemporaryDirectory(prefix="remrss-community-") as temp:
        file = Path(temp) / "release.zip"
        file.write_bytes(data)
        manifest, _ = verify_zip(file)
    verified = signed_fields(manifest)
    require(all(item[key] == verified[key] for key in SIGNED_FIELDS),
            f"{item['id']}: signed metadata differs from the catalogue")


def index_for(root):
    folder = root / "entries"
    require(folder.is_dir() and not folder.is_symlink(), "expected a regular entries directory")
    entries = sorted(folder.glob("*.json"))
    require(len(entries) <= MAX_ITEMS, "too many catalogue entries")
    items = []
    for path in entries:
        entry = validate(load(path, 8192))
        require(path.name == f"{entry['id']}.json", f"filename must match Mod ID: {path.name}")
        items.append(entry)
    index = {"schemaVersion": 1, "mods": items}
    require(len(serialize(index)) <= MAX_INDEX, "catalogue exceeds 256 KiB")
    return index


def serialize(obj):
    return (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def check(root, baseline, transfer=fetch):
    entries = index_for(root)
    target = root / "index.json"
    require(not target.is_symlink() and target.is_file() and
            target.stat().st_size <= MAX_INDEX and target.read_bytes() == serialize(entries),
            "run catalog.py build and commit the resulting index.json")
    previous = {item["id"]: item for item in load(baseline)["mods"]} if baseline else {}
    require(previous.keys() <= {item["id"] for item in entries["mods"]},
            "use withdrawn=true rather than deleting an ID")
    for item in entries["mods"]:
        old = previous.get(item["id"])
        if old:
            require(item["authorFingerprint"] == old["authorFingerprint"], f"{item['id']}: author differs")
            require(item["versionCode"] >= old["versionCode"], f"{item['id']}: version regressed")
            if item["versionCode"] == old["versionCode"]:
                pinned = SIGNED_FIELDS + ("sha256", "size", "downloadUrl")
                require(all(item[k] == old[k] for k in pinned), f"{item['id']}: use a higher versionCode")
        if item.get("withdrawn", False):
            require(old and item["versionCode"] == old["versionCode"], "withdraw only a listed version")
        elif not old or item["versionCode"] != old["versionCode"] or old.get("withdrawn", False):
            verify_payload(item, transfer)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("entry", help="print a submission record for this signed ZIP")
    make.add_argument("zip", type=Path)
    make.add_argument("download_url")
    make.add_argument("--summary", required=True)
    make.add_argument("--min-host-version-code", type=int, required=True)
    for command in ("build", "check"):
        config = sub.add_parser(command)
        config.add_argument("root", type=Path, nargs="?", default=Path("."))
        if command == "check":
            config.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "entry":
            sys.stdout.buffer.write(serialize(entry_from_zip(args.zip, args.download_url, args.summary,
                                                             args.min_host_version_code)))
        elif args.command == "build":
            (args.root / "index.json").write_bytes(serialize(index_for(args.root)))
        else:
            check(args.root, args.baseline)
    except (KeyError, ValueError, OSError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
