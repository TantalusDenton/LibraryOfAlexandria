from hashlib import sha256
from pathlib import PurePosixPath

from .config import settings


class Storage:
    def __init__(self):
        self.cfg = settings()
        self.root = (self.cfg.data_dir / "objects").resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.s3 = None
        self.blobs = None
        if self.cfg.storage_backend == "s3":
            import boto3

            self.s3 = boto3.client(
                "s3", endpoint_url=self.cfg.s3_endpoint_url, region_name=self.cfg.s3_region
            )
        elif self.cfg.storage_backend == "azure":
            from azure.storage.blob import BlobServiceClient

            from .azure_queue import credential

            if not self.cfg.azure_storage_account_url:
                raise ValueError("AZURE_STORAGE_ACCOUNT_URL is required for Azure storage")
            self.blobs = BlobServiceClient(
                account_url=self.cfg.azure_storage_account_url, credential=credential()
            ).get_container_client(self.cfg.azure_blob_container)
        elif self.cfg.storage_backend != "local":
            raise ValueError("Unsupported storage backend")

    def _path(self, key):
        if not key or key.startswith("/") or ".." in PurePosixPath(key).parts or "\\" in key:
            raise ValueError("Invalid storage path")
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Invalid storage path")
        return path

    def put(self, project_id: str, payload: bytes, extension: str, content_type: str) -> str:
        key = f"{project_id}/{sha256(payload).hexdigest()}.{extension}"
        path = self._path(key)
        if self.blobs is not None:
            from azure.core.exceptions import ResourceExistsError
            from azure.storage.blob import ContentSettings

            try:
                self.blobs.upload_blob(
                    key, payload, overwrite=False, content_settings=ContentSettings(content_type=content_type)
                )
            except ResourceExistsError:
                pass  # Content-addressed objects are immutable and safe to reuse.
        elif self.s3:
            self.s3.put_object(Bucket=self.cfg.s3_bucket, Key=key, Body=payload, ContentType=content_type)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                import os
                from tempfile import NamedTemporaryFile

                with NamedTemporaryFile(dir=path.parent, delete=False) as f:
                    f.write(payload)
                    temp = f.name
                os.replace(temp, path)
        return key

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if self.blobs is not None:
            from azure.core.exceptions import ResourceNotFoundError

            try:
                return self.blobs.download_blob(key).readall()
            except ResourceNotFoundError as exc:
                raise FileNotFoundError(key) from exc
        if self.s3:
            return self.s3.get_object(Bucket=self.cfg.s3_bucket, Key=key)["Body"].read()
        return path.read_bytes()
