"""MinIO 对象存储封装。"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from pathlib import Path
from typing import BinaryIO

from minio import Minio
from minio.error import S3Error

from config import settings

logger = logging.getLogger("minio.storage")


class MinioStorageError(Exception):
    """MinIO 存储异常。"""


class MinioStorageService:
    def __init__(self) -> None:
        self._client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        self._public_client = Minio(
            settings.MINIO_PUBLIC_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_PUBLIC_SECURE,
        )
        self._bucket_ready = False

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        try:
            if not self._client.bucket_exists(settings.MINIO_BUCKET):
                self._client.make_bucket(settings.MINIO_BUCKET)
                logger.info("MinIO bucket 已创建 bucket=%s", settings.MINIO_BUCKET)
            self._bucket_ready = True
        except S3Error as exc:
            logger.warning("MinIO bucket 初始化失败 bucket=%s code=%s", settings.MINIO_BUCKET, exc.code)
            raise MinioStorageError("MinIO 存储初始化失败") from exc

    def build_object_key(self, batch_id: object, filename: str) -> str:
        extension = Path(filename or "audio").suffix.lower()
        prefix = settings.MINIO_UPLOAD_PREFIX.strip("/")
        return f"{prefix}/{batch_id}/{uuid.uuid4().hex}{extension}"

    def upload(self, object_key: str, data: BinaryIO, length: int, content_type: str) -> None:
        self._ensure_bucket()
        try:
            self._client.put_object(
                settings.MINIO_BUCKET,
                object_key,
                data,
                length,
                content_type=content_type,
            )
            logger.info("MinIO 上传完成 bucket=%s object_key=%s size=%s content_type=%s", settings.MINIO_BUCKET, object_key, length, content_type)
        except S3Error as exc:
            logger.warning("MinIO 上传失败 bucket=%s object_key=%s code=%s", settings.MINIO_BUCKET, object_key, exc.code)
            raise MinioStorageError("音频上传到对象存储失败") from exc

    def remove(self, object_key: str | None) -> bool:
        if not object_key:
            return True
        self._ensure_bucket()
        try:
            self._client.remove_object(settings.MINIO_BUCKET, object_key)
            logger.info("MinIO 对象已删除 bucket=%s object_key=%s", settings.MINIO_BUCKET, object_key)
            return True
        except S3Error:
            logger.warning("MinIO 对象删除失败 bucket=%s object_key=%s", settings.MINIO_BUCKET, object_key, exc_info=True)
            return False

    def exists(self, object_key: str | None) -> bool:
        if not object_key:
            return False
        self._ensure_bucket()
        try:
            self._client.stat_object(settings.MINIO_BUCKET, object_key)
            return True
        except S3Error:
            return False

    def presigned_get_url(self, object_key: str, expires: timedelta) -> str:
        self._ensure_bucket()
        try:
            return self._public_client.presigned_get_object(
                settings.MINIO_BUCKET,
                object_key,
                expires=expires,
            )
        except S3Error as exc:
            logger.warning("MinIO 预签名 URL 生成失败 bucket=%s object_key=%s code=%s", settings.MINIO_BUCKET, object_key, exc.code)
            raise MinioStorageError("音频下载链接生成失败") from exc


minio_storage_service = MinioStorageService()
