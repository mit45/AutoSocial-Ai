"""Deprecated compatibility module.

Historically provided helper functions for Cloudflare R2.
The real implementation now lives in `app.services.storage_backend`.
This module re-exports the same symbols for backward compatibility.
"""
from app.services.storage_backend import (  # type: ignore
    upload_bytes,
    delete_key,
    url_for_key,
    generate_presigned_get_from_url,
)

