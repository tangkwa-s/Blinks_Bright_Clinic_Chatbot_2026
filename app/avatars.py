"""User avatars — uploaded images plus the seeded staff-portrait pool.

`User.avatar` holds a public path (e.g. ``/assets/images/avatars/…`` for an upload,
or a committed pool portrait under ``/assets/images/staff-avatars/``). The frontend
``avatarHTML`` falls back to initials when the path is missing, so a stale path is
harmless. ``backfill_avatars`` runs on startup to give every avatar-less user a
pool portrait — this populates both a fresh seed and an existing database without
overwriting anyone's uploaded photo.
"""
import secrets
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app import models

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
AVATAR_DIR = WEB_DIR / "assets" / "images" / "avatars"   # runtime uploads (gitignored)
CHAT_UPLOAD_DIR = WEB_DIR / "assets" / "images" / "chat-uploads"  # customer chat photos (gitignored)
SERVICE_UPLOAD_DIR = WEB_DIR / "assets" / "images" / "service-uploads"  # runtime uploads (gitignored)
IMG_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}

# Committed seed portraits, by role flavour.
DOCTOR_AVATARS = [f"/assets/images/staff-avatars/doctor-{i}.png" for i in range(1, 5)]
STAFF_AVATARS = [f"/assets/images/staff-avatars/staff-{i}.png" for i in range(1, 7)]


def _store_upload(file: UploadFile, slug: str, dest_dir: Path, url_dir: str) -> str:
    """Validate an uploaded image (type + size) and write it under ``dest_dir``;
    return its public ``/assets/images/<url_dir>/…`` path."""
    ext = IMG_EXT.get(file.content_type)
    if not ext:
        raise HTTPException(status_code=400, detail="Please upload a PNG, JPG or WebP image")
    data = file.file.read()
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty")
    if len(data) > 4 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image is too large (max 4 MB)")
    dest_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{slug}-{secrets.token_hex(4)}.{ext}"
    (dest_dir / fname).write_bytes(data)
    return f"/assets/images/{url_dir}/{fname}"


def save_avatar(file: UploadFile, slug: str) -> str:
    """Validate and store an uploaded avatar image; return its public path."""
    return _store_upload(file, slug, AVATAR_DIR, "avatars")


def save_service_image(file: UploadFile, slug: str) -> str:
    """Validate and store an uploaded treatment/menu image; return its public path."""
    return _store_upload(file, slug, SERVICE_UPLOAD_DIR, "service-uploads")


def save_chat_image(file: UploadFile, slug: str) -> str:
    """Validate and store a photo a customer sent in chat; return its public path."""
    return _store_upload(file, slug, CHAT_UPLOAD_DIR, "chat-uploads")


def _pool_avatar(role: str, doc_i: int, staff_i: int) -> str:
    return (DOCTOR_AVATARS[doc_i % len(DOCTOR_AVATARS)] if role == "doctor"
            else STAFF_AVATARS[staff_i % len(STAFF_AVATARS)])


def backfill_avatars(db) -> int:
    """Assign a pool portrait to every login User and StaffMember that has none
    (idempotent)."""
    n = 0
    users = (db.query(models.User)
             .filter((models.User.avatar == "") | (models.User.avatar.is_(None)))
             .order_by(models.User.id).all())
    doc_i = staff_i = 0
    for u in users:
        u.avatar = _pool_avatar(u.role, doc_i, staff_i)
        if u.role == "doctor":
            doc_i += 1
        else:
            staff_i += 1
    n += len(users)

    members = (db.query(models.StaffMember)
               .filter((models.StaffMember.avatar == "") | (models.StaffMember.avatar.is_(None)))
               .order_by(models.StaffMember.id).all())
    doc_i = staff_i = 0
    for m in members:
        m.avatar = _pool_avatar(m.role, doc_i, staff_i)
        if m.role == "doctor":
            doc_i += 1
        else:
            staff_i += 1
    n += len(members)

    if n:
        db.commit()
    return n
