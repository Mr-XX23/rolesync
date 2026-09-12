"""Pluggable storage for raw ingested file bytes.

Backends (RAW_STORE_BACKEND):
  local  - files on disk under VAULT_STORAGE_DIR (default; needs no service)
  s3     - any S3-compatible object store: MinIO, Cloudflare R2, Backblaze B2, AWS S3

Because everything goes through the S3 API, moving from the self-hosted MinIO
service to a cloud provider is an env-var change, not a code change.

A storage reference is an opaque string recorded on the document:
    "s3://bucket/key"   (object store)
    "/abs/path/to/file" (local disk)
so legacy records written before this abstraction still read back correctly.

Config (env):
  RAW_STORE_BACKEND            local | s3           (default: local)
  RAW_STORE_BUCKET             bucket name          (default: rolesync-raw-docs)
  RAW_STORE_ENDPOINT_URL       e.g. http://minio:9000 (omit for AWS S3)
  RAW_STORE_ACCESS_KEY_ID / RAW_STORE_SECRET_ACCESS_KEY
  RAW_STORE_REGION             default: us-east-1
  RAW_STORE_FORCE_PATH_STYLE   true for MinIO (default: false)
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

try:
    import boto3
    from botocore.config import Config as BotoConfig
except ImportError:  # pragma: no cover - boto3 ships with the service image
    boto3 = None
    BotoConfig = None

_TRUTHY = {"1", "true", "yes", "on"}
S3_PREFIX = "s3://"


def _default_storage_dir() -> str:
    return os.path.join(os.path.dirname(__file__), "..", "storage", "vault_files")


class RawObjectStore:
    """Stores and retrieves raw document bytes behind a stable interface."""

    def __init__(
        self,
        backend: Optional[str] = None,
        bucket: Optional[str] = None,
        storage_dir: Optional[str] = None,
    ) -> None:
        self.backend = (backend or os.environ.get("RAW_STORE_BACKEND", "local")).strip().lower()
        self.bucket = (bucket or os.environ.get("RAW_STORE_BUCKET", "rolesync-raw-docs")).strip()
        self.storage_dir = Path(storage_dir or os.environ.get("VAULT_STORAGE_DIR", _default_storage_dir()))
        try:
            self.storage_dir.mkdir(parents=True, exist_ok=True)
        except Exception as err:  # pragma: no cover - unwritable volume
            print(f"[RawObjectStore] Could not create local storage dir: {err}")

        self._client = None
        self._client_attempted = False
        self._bucket_ready = False

    # ---- s3 plumbing -----------------------------------------------------
    def _s3(self):
        """Lazily build the S3 client once; None means the object store is unusable."""
        if self._client_attempted:
            return self._client
        self._client_attempted = True

        if self.backend != "s3":
            return None
        if boto3 is None:
            print("[RawObjectStore] boto3 not installed - falling back to local disk.")
            return None

        endpoint = os.environ.get("RAW_STORE_ENDPOINT_URL", "").strip() or None
        access_key = os.environ.get("RAW_STORE_ACCESS_KEY_ID", "").strip() or None
        secret_key = os.environ.get("RAW_STORE_SECRET_ACCESS_KEY", "").strip() or None
        region = os.environ.get("RAW_STORE_REGION", "us-east-1").strip() or "us-east-1"
        path_style = os.environ.get("RAW_STORE_FORCE_PATH_STYLE", "").strip().lower() in _TRUTHY

        try:
            config = BotoConfig(
                signature_version="s3v4",
                # MinIO (and some self-hosted gateways) require path-style addressing.
                s3={"addressing_style": "path" if path_style else "auto"},
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=5,
                read_timeout=30,
            )
            self._client = boto3.client(
                "s3",
                endpoint_url=endpoint,
                region_name=region,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                config=config,
            )
            print(f"[RawObjectStore] S3 backend ready (endpoint={endpoint or 'aws'}, bucket={self.bucket}).")
        except Exception as err:
            print(f"[RawObjectStore] Could not initialise S3 client ({err}); falling back to local disk.")
            self._client = None
        return self._client

    def _ensure_bucket(self, client) -> bool:
        """Create the bucket on first use so there is no manual setup step."""
        if self._bucket_ready:
            return True
        try:
            client.head_bucket(Bucket=self.bucket)
            self._bucket_ready = True
            return True
        except Exception:
            pass

        try:
            client.create_bucket(Bucket=self.bucket)
            print(f"[RawObjectStore] Created bucket '{self.bucket}'.")
            self._bucket_ready = True
        except Exception as err:
            # Another worker may have created it in the meantime.
            try:
                client.head_bucket(Bucket=self.bucket)
                self._bucket_ready = True
            except Exception:
                print(f"[RawObjectStore] Bucket '{self.bucket}' unavailable: {err}")
                self._bucket_ready = False
        return self._bucket_ready

    # ---- local plumbing --------------------------------------------------
    @staticmethod
    def _safe_key(key: str) -> str:
        """Reject traversal and absolute paths before touching the filesystem."""
        cleaned = (key or "").replace("\\", "/").strip("/")
        parts = [p for p in cleaned.split("/") if p not in ("", ".", "..")]
        return "/".join(parts) or "unnamed"

    def _put_local(self, key: str, data: bytes) -> Optional[str]:
        try:
            target = self.storage_dir / self._safe_key(key)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            return str(target)
        except Exception as err:
            print(f"[RawObjectStore] Local write failed for {key}: {err}")
            return None

    # ---- public API ------------------------------------------------------
    def available(self) -> bool:
        """True when the configured backend can actually be reached."""
        if self.backend != "s3":
            return True
        client = self._s3()
        return client is not None and self._ensure_bucket(client)

    def put(self, key: str, data: bytes, content_type: str = "") -> Optional[str]:
        """Store bytes and return a storage reference (None if nothing could be written)."""
        if not data:
            return None

        key = self._safe_key(key)
        if self.backend == "s3":
            client = self._s3()
            if client is not None and self._ensure_bucket(client):
                try:
                    extra = {"ContentType": content_type} if content_type else {}
                    client.put_object(Bucket=self.bucket, Key=key, Body=data, **extra)
                    return f"{S3_PREFIX}{self.bucket}/{key}"
                except Exception as err:
                    print(f"[RawObjectStore] S3 put failed for {key}; falling back to local disk: {err}")

        # Local disk is both the default backend and the safety net for an
        # unreachable object store, so ingestion never loses the original file.
        return self._put_local(key, data)

    def get(self, ref: str) -> Optional[bytes]:
        """Read bytes back from a storage reference (object store or local path)."""
        if not ref:
            return None

        if ref.startswith(S3_PREFIX):
            bucket, _, key = ref[len(S3_PREFIX):].partition("/")
            client = self._s3()
            if client is None or not key:
                return None
            try:
                return client.get_object(Bucket=bucket, Key=key)["Body"].read()
            except Exception as err:
                print(f"[RawObjectStore] S3 read failed for {ref}: {err}")
                return None

        try:
            path = Path(ref)
            if path.exists():
                return path.read_bytes()
        except Exception as err:
            print(f"[RawObjectStore] Local read failed for {ref}: {err}")
        return None

    def delete(self, ref: str) -> bool:
        """Remove a stored object. Missing objects count as deleted."""
        if not ref:
            return False

        if ref.startswith(S3_PREFIX):
            bucket, _, key = ref[len(S3_PREFIX):].partition("/")
            client = self._s3()
            if client is None or not key:
                return False
            try:
                client.delete_object(Bucket=bucket, Key=key)
                return True
            except Exception as err:
                print(f"[RawObjectStore] S3 delete failed for {ref}: {err}")
                return False

        try:
            path = Path(ref)
            if path.exists():
                path.unlink()
            return True
        except Exception as err:
            print(f"[RawObjectStore] Local delete failed for {ref}: {err}")
            return False


# Shared instance used by the raw document store.
raw_object_store = RawObjectStore()
