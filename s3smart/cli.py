#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
s3smart: high-throughput S3 copy/sync with resume, checksums, browse mode
"""

import argparse
import hashlib
import json
import os
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse
import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError
from tqdm import tqdm

# --------------------------
# Constants
# --------------------------

S3_PREFIX = "s3://"
DEFAULT_PART_MB = 64
DEFAULT_WORKERS = 16

CONFIG_PATH_HOME = Path.home() / ".s3smart.json"
CONFIG_PATH_LOCAL = Path.cwd() / "s3smart.json"

# --------------------------
# Config loader
# --------------------------

def load_config(config_path: Path | None = None) -> dict:
    """
    Load s3smart configuration. If missing, auto-generate a default config
    with descriptive comments.
    """
    def read_json(path: Path):
        with open(path) as f:
            return json.load(f)

    # Priority: custom path
    if config_path and config_path.exists():
        cfg = read_json(config_path)
        print(f"🔧 Loaded config from custom path: {config_path}")
        return cfg

    # Local project config
    if CONFIG_PATH_LOCAL.exists():
        cfg = read_json(CONFIG_PATH_LOCAL)
        print(f"🔧 Loaded config from local project: {CONFIG_PATH_LOCAL}")
        return cfg

    # Home config
    if CONFIG_PATH_HOME.exists():
        cfg = read_json(CONFIG_PATH_HOME)
        print(f"🔧 Loaded config from user home: {CONFIG_PATH_HOME}")
        return cfg

    # No config found → create default
    default_cfg = {
        "_comment": "Default configuration file for s3smart. Adjust values to tune performance.",
        "_note_browse_part_size_mb": "Chunk size (in MB) used during interactive browse uploads/downloads.",
        "browse_part_size_mb": 128,
        "_note_default_part_size_mb": "Default chunk size (in MB) for bulk upload/download operations.",
        "default_part_size_mb": 256,
        "_note_default_workers": "Number of parallel threads for concurrent transfers.",
        "default_workers": 18
    }

    print("⚙️ No existing configuration found.")
    print(f"🪄 Creating default configuration at {CONFIG_PATH_LOCAL}")
    with open(CONFIG_PATH_LOCAL, "w") as f:
        json.dump(default_cfg, f, indent=2)
    print(f"✅ Default config created: {CONFIG_PATH_LOCAL}")
    return default_cfg

# --------------------------
# Helpers
# --------------------------

def is_s3_uri(uri: str) -> bool:
    return uri.lower().startswith(S3_PREFIX)


class S3Url:
    def __init__(self, bucket: str, key: str):
        self.bucket = bucket
        self.key = key


def parse_s3_url(uri: str) -> S3Url:
    if not is_s3_uri(uri):
        raise ValueError(f"Not an S3 URI: {uri}")
    p = urlparse(uri)
    return S3Url(p.netloc, p.path.lstrip("/"))


def md5_of_file(path: str, chunk: int = 8 * 1024 * 1024) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def ensure_parent(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)

# --------------------------
# Rate limiter
# --------------------------

class RateLimiter:
    def __init__(self, max_bytes_per_sec: float | None):
        self.rate = max_bytes_per_sec or 0.0
        self.tokens = 0.0
        self.last = time.monotonic()
        self.lock = threading.Lock()

    def consume(self, nbytes: int) -> None:
        if not self.rate or self.rate <= 0:
            return
        with self.lock:
            while True:
                now = time.monotonic()
                elapsed = now - self.last
                self.last = now
                self.tokens += elapsed * self.rate
                if self.tokens > self.rate:
                    self.tokens = self.rate
                if self.tokens >= nbytes:
                    self.tokens -= nbytes
                    return
                need = nbytes - self.tokens
                sleep_for = need / self.rate
                self.lock.release()
                try:
                    time.sleep(min(sleep_for, 0.1))
                finally:
                    self.lock.acquire()

# --------------------------
# S3 client
# --------------------------

def make_s3_client(region: str | None,
                   max_pool: int,
                   retries: int,
                   endpoint_url: str | None):
    cfg = BotoConfig(
        retries={"max_attempts": max(3, retries), "mode": "standard"},
        max_pool_connections=max(10, max_pool),
        signature_version="s3v4",
    )
    return boto3.client("s3",
                        region_name=region,
                        endpoint_url=endpoint_url,
                        config=cfg)

# --------------------------
# Multipart upload
# --------------------------

def multipart_upload(s3,
                     local_path: str,
                     s3url: S3Url,
                     workers: int,
                     part_size: int,
                     progress,
                     rate: RateLimiter):
    fsize = os.path.getsize(local_path)
    mpu = s3.create_multipart_upload(Bucket=s3url.bucket, Key=s3url.key)
    upload_id = mpu["UploadId"]

    parts = []
    with open(local_path, "rb") as f:
        idx = 1
        while True:
            data = f.read(part_size)
            if not data:
                break
            rate.consume(len(data))
            resp = s3.upload_part(
                Bucket=s3url.bucket,
                Key=s3url.key,
                PartNumber=idx,
                UploadId=upload_id,
                Body=data
            )
            parts.append({"PartNumber": idx, "ETag": resp["ETag"]})
            idx += 1
            progress.update(len(data))

    s3.complete_multipart_upload(
        Bucket=s3url.bucket,
        Key=s3url.key,
        UploadId=upload_id,
        MultipartUpload={"Parts": parts},
    )

# --------------------------
# Parallel download
# --------------------------

def parallel_download(s3,
                      s3url: S3Url,
                      local_path: str,
                      workers: int,
                      part_size: int,
                      progress,
                      rate: RateLimiter):
    head = s3.head_object(Bucket=s3url.bucket, Key=s3url.key)
    size = head["ContentLength"]

    ensure_parent(local_path)
    with open(local_path, "wb") as f:
        f.truncate(size)

    ranges = [(i, min(i + part_size, size) - 1)
              for i in range(0, size, part_size)]

    from concurrent.futures import ThreadPoolExecutor
    def worker(rng):
        start, end = rng
        resp = s3.get_object(Bucket=s3url.bucket,
                             Key=s3url.key,
                             Range=f"bytes={start}-{end}")
        chunk = resp["Body"].read()
        rate.consume(len(chunk))
        with open(local_path, "r+b") as f:
            f.seek(start)
            f.write(chunk)
        progress.update(len(chunk))

    with ThreadPoolExecutor(max_workers=workers) as ex:
        ex.map(worker, ranges)

# --------------------------
# Commands
# --------------------------

def cmd_upload(args, s3, config) -> dict:
    stats = {"uploaded": 0, "downloaded": 0, "skipped": 0, "failed": 0}
    src = args.src
    dest = parse_s3_url(args.dest)
    for root, _, files in os.walk(src):
        for f in files:
            local = os.path.join(root, f)
            key = os.path.relpath(local, src).replace("\\", "/")
            s3url = S3Url(dest.bucket, dest.key.rstrip("/") + "/" + key)
            try:
                fsize = os.path.getsize(local)
                print(f"Uploading {local} -> s3://{s3url.bucket}/{s3url.key}")
                pbar = tqdm(total=fsize, unit="B", unit_scale=True,
                            desc="Upload", dynamic_ncols=True)
                multipart_upload(s3, local, s3url,
                                 args.workers,
                                 args.part_size,
                                 pbar,
                                 RateLimiter(args.max_mbps))
                pbar.close()
                stats["uploaded"] += 1
            except Exception as e:
                print(f"Upload failed: {e}")
                stats["failed"] += 1
    return stats


def cmd_download(args, s3, config) -> dict:
    stats = {"uploaded": 0, "downloaded": 0, "skipped": 0, "failed": 0}
    src = parse_s3_url(args.src)
    dest = args.dest
    resp = s3.list_objects_v2(Bucket=src.bucket, Prefix=src.key)
    for obj in resp.get("Contents", []):
        key = obj["Key"]
        out = os.path.join(dest, os.path.basename(key))
        try:
            size = obj["Size"]
            print(f"Downloading s3://{src.bucket}/{key} -> {out}")
            pbar = tqdm(total=size, unit="B", unit_scale=True,
                        desc="Download", dynamic_ncols=True)
            parallel_download(s3, S3Url(src.bucket, key), out,
                              args.workers, args.part_size,
                              pbar, RateLimiter(args.max_mbps))
            pbar.close()
            stats["downloaded"] += 1
        except Exception as e:
            print(f"Download failed: {e}")
            stats["failed"] += 1
    return stats

# --------------------------
# Browse
# --------------------------

def cmd_browse(args, s3, config):
    def list_buckets():
        resp = s3.list_buckets()
        return [b["Name"] for b in resp.get("Buckets", [])]

    def list_prefix(bucket, prefix):
        paginator = s3.get_paginator("list_objects_v2")
        items = []
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix, Delimiter="/"):
            for cp in page.get("CommonPrefixes", []):
                items.append(("DIR", cp["Prefix"]))
            for obj in page.get("Contents", []):
                if obj["Key"] != prefix:
                    items.append(("FILE", obj["Key"], obj["Size"]))
        return items

    bucket = None
    prefix = ""

    while True:
        if not bucket:
            buckets = list_buckets()
            print("\nBuckets:")
            for i, b in enumerate(buckets, 1):
                print(f"{i}. {b}")
            choice = input("Choose bucket (q=quit): ")
            if choice.lower() == "q":
                break
            if choice.isdigit() and 1 <= int(choice) <= len(buckets):
                bucket = buckets[int(choice) - 1]
                prefix = ""
            continue

        print(f"\nBrowsing s3://{bucket}/{prefix}")
        items = list_prefix(bucket, prefix)
        for i, itm in enumerate(items, 1):
            if itm[0] == "DIR":
                print(f"{i}. DIR  {itm[1]}")
            else:
                print(f"{i}. FILE {itm[1]} ({itm[2]} bytes)")

        choice = input("Enter number, '..'=up, 'd <num>'=download, 'u <path>'=upload, 'q'=quit: ")

        if not getattr(args, "explicit_part_size", False):
            args.part_size = config.get("browse_part_size_mb", 8) * 1024 * 1024
        print(f"[Config] browse part size = {args.part_size // 1024 // 1024} MB")

        if choice.lower() == "q":
            break
        if choice == "..":
            if "/" in prefix.strip("/"):
                prefix = "/".join(prefix.strip("/").split("/")[:-1]) + "/"
            else:
                bucket = None
                prefix = ""
            continue
        if choice.startswith("d "):
            num = int(choice.split()[1])
            itm = items[num - 1]
            if itm[0] == "FILE":
                key = itm[1]
                out = os.path.basename(key)
                size = itm[2]
                print(f"Downloading s3://{bucket}/{key} -> {out}")
                pbar = tqdm(total=size, unit="B", unit_scale=True,
                            desc="Download", dynamic_ncols=True)
                parallel_download(s3, S3Url(bucket, key), out,
                                  args.workers, args.part_size,
                                  pbar, RateLimiter(args.max_mbps))
                pbar.close()
        elif choice.startswith("u "):
            path = choice[2:].strip()
            if os.path.isfile(path):
                fname = os.path.basename(path)
                key = prefix + fname
                fsize = os.path.getsize(path)
                print(f"Uploading {path} -> s3://{bucket}/{key}")
                pbar = tqdm(total=fsize, unit="B", unit_scale=True,
                            desc="Upload", dynamic_ncols=True)
                multipart_upload(s3, path, S3Url(bucket, key),
                                 args.workers, args.part_size,
                                 pbar, RateLimiter(args.max_mbps))
                pbar.close()
            else:
                print("Path not found or not a file.")
        elif choice.isdigit():
            num = int(choice)
            itm = items[num - 1]
            if itm[0] == "DIR":
                prefix = itm[1]

# --------------------------
# Parser 
# --------------------------

def positive_int_mb(val: str) -> int:
    return int(val) * 1024 * 1024


class StoreExplicit(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, values)
        setattr(namespace, "explicit_part_size", True)


def build_parser(config: dict) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="s3smart")
    p.add_argument("--region")
    p.add_argument("--endpoint-url")
    p.add_argument("--retries", type=int, default=8)
    p.add_argument("--max-pool", type=int, default=64)
    p.add_argument("--config", type=str, help="Path to a custom s3smart.json configuration file")

    sub = p.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--workers", type=int, default=config.get("default_workers", DEFAULT_WORKERS))
    common.add_argument("--part-size", type=positive_int_mb,
                        default=config.get("default_part_size_mb", DEFAULT_PART_MB) * 1024 * 1024,
                        action=StoreExplicit)
    common.add_argument("--checksum", action="store_true")
    common.add_argument("--max-mbps", type=float)
    common.add_argument("--force", action="store_true")

    up = sub.add_parser("upload", parents=[common])
    up.add_argument("src")
    up.add_argument("dest")

    down = sub.add_parser("download", parents=[common])
    down.add_argument("src")
    down.add_argument("dest")

    sy = sub.add_parser("sync", parents=[common])
    sy.add_argument("src")
    sy.add_argument("dest")

    sub.add_parser("browse", parents=[common])
    return p


# --------------------------
# Main
# --------------------------

def main():
    os.system("cls" if os.name == "nt" else "clear")
    print("s3smart - Fast, Reliable AWS S3 Transfers & Sync Utility\n")
    # print("=== S3SMART Utility ===\n")

    base_parser = argparse.ArgumentParser(add_help=False)
    base_parser.add_argument("--config", type=str)
    temp_args, _ = base_parser.parse_known_args()

    config_path = Path(temp_args.config).expanduser() if temp_args.config else None
    config = load_config(config_path)

    args = build_parser(config).parse_args()
    s3 = make_s3_client(args.region, args.max_pool, args.retries, getattr(args, "endpoint_url", None))

    try:
        if args.cmd == "upload":
            stats = cmd_upload(args, s3, config)
        elif args.cmd == "download":
            stats = cmd_download(args, s3, config)
        elif args.cmd == "sync":
            stats = cmd_sync(args, s3, config)
        elif args.cmd == "browse":
            cmd_browse(args, s3, config)
            return
        else:
            stats = {}

        print("\nSummary: uploaded={u}, downloaded={d}, skipped={s}, failed={f}"
              .format(u=stats.get("uploaded", 0),
                      d=stats.get("downloaded", 0),
                      s=stats.get("skipped", 0),
                      f=stats.get("failed", 0)))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
