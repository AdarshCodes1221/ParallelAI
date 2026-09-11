from __future__ import annotations

import logging

from core.config import get_settings

logger = logging.getLogger(__name__)


class ObjectStorage:
    """S3-compatible original-file storage; disabled when no bucket is configured."""

    def __init__(self):
        settings = get_settings()
        self.bucket = settings.s3_bucket
        self.client = None
        if self.bucket:
            import boto3
            self.client = boto3.client(
                "s3",
                endpoint_url=settings.s3_endpoint_url or None,
                region_name=settings.s3_region,
                aws_access_key_id=settings.s3_access_key or None,
                aws_secret_access_key=settings.s3_secret_key or None,
            )

    @property
    def enabled(self) -> bool:
        return self.client is not None and bool(self.bucket)

    def put(self, key: str, content: bytes, content_type: str) -> None:
        if self.enabled:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=content, ContentType=content_type)

    def delete(self, key: str) -> None:
        if self.enabled:
            self.client.delete_object(Bucket=self.bucket, Key=key)