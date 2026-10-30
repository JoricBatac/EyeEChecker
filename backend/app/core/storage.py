"""Photo storage. Photos are temporary: deleted after sign-off or draft expiry (PRD 11.1)."""

from __future__ import annotations

import hashlib
import hmac
import time
from functools import lru_cache
from pathlib import Path
from typing import Protocol
from urllib.parse import urlencode

from app.core.config import Settings, get_settings


class Storage(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...
    def signed_url(self, key: str, ttl_seconds: int) -> str: ...


class LocalStorage:
    """Filesystem storage for development and tests."""

    def __init__(self, root: Path, secret: str):
        self.root = root
        self.secret = secret.encode()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents:
            raise ValueError("invalid storage key")
        return p

    def put(self, key: str, data: bytes, content_type: str) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def signed_url(self, key: str, ttl_seconds: int) -> str:
        expires = int(time.time()) + ttl_seconds
        sig = hmac.new(self.secret, f"{key}:{expires}".encode(), hashlib.sha256).hexdigest()
        return f"/v1/local-storage/{key}?" + urlencode({"expires": expires, "sig": sig})

    def verify(self, key: str, expires: int, sig: str) -> bool:
        if expires < time.time():
            return False
        expected = hmac.new(self.secret, f"{key}:{expires}".encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sig)


class S3Storage:
    """S3-compatible storage: MinIO locally, Google Cloud Storage (asia-southeast1) via its S3 interop API."""

    def __init__(self, settings: Settings):
        import boto3
        from botocore.config import Config

        common = dict(
            region_name=settings.storage_region,
            aws_access_key_id=settings.storage_access_key,
            aws_secret_access_key=settings.storage_secret_key,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        self.bucket = settings.storage_bucket
        self.client = boto3.client("s3", endpoint_url=settings.storage_endpoint_url, **common)
        self.url_client = boto3.client(
            "s3",
            endpoint_url=settings.storage_public_endpoint_url or settings.storage_endpoint_url,
            **common,
        )

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def get(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    def signed_url(self, key: str, ttl_seconds: int) -> str:
        return self.url_client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=ttl_seconds
        )


def build_storage(settings: Settings) -> Storage:
    if settings.storage_backend == "s3":
        return S3Storage(settings)
    return LocalStorage(settings.local_storage_dir, settings.jwt_secret)


@lru_cache
def _default_storage() -> Storage:
    return build_storage(get_settings())


def get_storage() -> Storage:
    return _default_storage()


def photo_key(org_id: str, encounter_id: str, photo_id: str) -> str:
    return f"encounter-photos/{org_id}/{encounter_id}/{photo_id}.jpg"
