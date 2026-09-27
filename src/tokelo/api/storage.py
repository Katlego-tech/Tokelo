"""The `api`'s S3 client (docs/design/api.md §6; docs/design/web.md §6, the CSP).

The `api` hands the browser two signed URLs: the upload POST (T025) and a dossier's download
link (T042). The browser uses both straight against the bucket, so both must be signed the way S3
and the page will both accept:

- **Signature Version 4.** botocore still presigns with Signature Version 2 unless it's told
  otherwise, whatever it uses for its own calls. S3 has deprecated SigV2.
- **The bucket's regional, virtual-hosted address,** `<bucket>.s3.<region>.amazonaws.com`. The
  web app's Content-Security-Policy allows that host and no other for uploads (static.py). Left
  to itself, botocore signs for the global `<bucket>.s3.amazonaws.com`, and the page refuses to
  post the file there.

The `api`'s own calls, which reach S3 through the gateway endpoint, use the same client. They
were already regional, so nothing changes for them.
"""

from typing import Any

import boto3
from botocore.config import Config

SIGNING = Config(signature_version="s3v4", s3={"addressing_style": "virtual"})


def client() -> Any:
    """A new S3 client. boto3 ships no types; each module keeps one per container."""
    return boto3.client("s3", config=SIGNING)
