from hashlib import sha256
from pathlib import PurePosixPath

from .config import settings


class Storage:
    def __init__(self):
        self.cfg = settings()
        self.root = (self.cfg.data_dir / "objects").resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.s3 = None
        if self.cfg.storage_backend == "s3":
            import boto3

            self.s3 = boto3.client(
                "s3", endpoint_url=self.cfg.s3_endpoint_url, region_name=self.cfg.s3_region
            )

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
        if self.s3:
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
        if self.s3:
            return self.s3.get_object(Bucket=self.cfg.s3_bucket, Key=key)["Body"].read()
        return path.read_bytes()
