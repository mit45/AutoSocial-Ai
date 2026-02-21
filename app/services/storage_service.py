"""Compatibility layer that re-exports the unified storage backend API.

Older modules import functions from `app.services.storage_service`.
This module delegates to `app.services.storage_backend`.
"""
from app.services.storage_backend import (  # type: ignore
    ensure_storage_dir,
    upload_to_remote_server,
    save_png_bytes_to_generated,
    delete_remote_file,
)

__all__ = [
    "ensure_storage_dir",
    "upload_to_remote_server",
    "save_png_bytes_to_generated",
    "delete_remote_file",
]

