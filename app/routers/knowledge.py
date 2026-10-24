"""Knowledge base routes — articles CRUD, document upload and embedding reindex."""
import io
import re
from pathlib import Path

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app import models
from app.ai import rag
from app.database import get_db
from app.deps import active_clinic_id, current_user, require_role
from app.scope import scoped

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

EDITOR = require_role("branch_manager", "marketing")

UPLOAD_MAX_BYTES = 10 * 1024 * 1024
# Each article becomes ONE embedding input (rag.py builds a single chunk per
# article) and client.py::embed_texts fails the WHOLE batch on one oversized
# input (~8k tokens for text-embedding-3-small; Thai runs near 1 token/char),
# so extracted text must stay well under that.
BODY_MAX_CHARS = 12_000


def _reindex_async(cid: int) -> None:
    """Refresh the clinic's KB index off the request path so new/edited articles flow
    into AI retrieval automatically (no manual reindex needed)."""
    import threading
    from app.routers.clinics import _index_clinic_kb
    threading.Thread(target=_index_clinic_kb, args=(cid,), daemon=True).start()


def article_dict(a: models.KBArticle) -> dict:
    return {
        "id": a.id, "type": a.type, "title": a.title, "content": a.content,
        "branch_id": a.branch_id, "active": a.active,
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
    }


@router.get("/articles")
def list_articles(db: Session = Depends(get_db), _u=Depends(current_user),
                  cid: int = Depends(active_clinic_id)):
    rows = scoped(db, models.KBArticle, cid).order_by(models.KBArticle.type,
                                                      models.KBArticle.id).all()
    return [article_dict(a) for a in rows]


@router.post("/articles")
def create_article(data: dict = Body(...),
                   db: Session = Depends(get_db), _u=Depends(EDITOR),
                   cid: int = Depends(active_clinic_id)):
    a = models.KBArticle(
        type=data.get("type", "general"),
        title=data.get("title", "Untitled"),
        content=data.get("content", ""),
        branch_id=data.get("branch_id"),
        active=data.get("active", True),
        clinic_id=cid,
    )
    db.add(a)
    db.commit()
    _reindex_async(cid)
    return article_dict(a)


@router.patch("/articles/{aid}")
def update_article(aid: int, data: dict = Body(...),
                   db: Session = Depends(get_db), _u=Depends(EDITOR),
                   cid: int = Depends(active_clinic_id)):
    a = scoped(db, models.KBArticle, cid).filter(models.KBArticle.id == aid).first()
    if not a:
        raise HTTPException(status_code=404, detail="Article not found")
    for field in ("type", "title", "content", "branch_id", "active"):
        if field in data:
            setattr(a, field, data[field])
    db.commit()
    _reindex_async(cid)
    return article_dict(a)


@router.delete("/articles/{aid}")
def delete_article(aid: int, db: Session = Depends(get_db), _u=Depends(EDITOR),
                   cid: int = Depends(active_clinic_id)):
    a = scoped(db, models.KBArticle, cid).filter(models.KBArticle.id == aid).first()
    if a:
        db.delete(a)
        db.commit()
        _reindex_async(cid)
    return {"ok": True}


def _extract_pdf(data: bytes) -> str:
    # Lazy import: a missing/broken lib degrades to a per-request 400, not an app-wide crash.
    from pypdf import PdfReader
    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Could not read this PDF — it may be corrupt or password-protected")


def _extract_docx(data: bytes) -> str:
    import docx
    try:
        doc = docx.Document(io.BytesIO(data))
        parts = [p.text for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    parts.append(" | ".join(cells))
        return "\n".join(parts)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Could not read this Word file — save it as .docx and try again")


def _extract_txt(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        # Legacy Thai text files are often TIS-620/cp874.
        try:
            return data.decode("cp874")
        except UnicodeDecodeError:
            return data.decode("utf-8", errors="replace")


def _normalize(text: str) -> str:
    """Clean extracted text: drop control chars, trim line ends, collapse blank
    runs (keeping paragraph breaks) and cap the length for embedding."""
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    lines = [ln.rstrip() for ln in text.splitlines()]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return text[:BODY_MAX_CHARS]


_EXTRACTORS = {".pdf": _extract_pdf, ".docx": _extract_docx, ".txt": _extract_txt}


@router.post("/upload")
def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db),
                    _u=Depends(EDITOR), cid: int = Depends(active_clinic_id)):
    """Turn an uploaded .pdf/.docx/.txt into a KB article (extract → normalize → index)."""
    filename = file.filename or ""
    # Key off the extension, not content_type — browsers send octet-stream for docx.
    ext = Path(filename).suffix.lower()
    extractor = _EXTRACTORS.get(ext)
    if not extractor:
        raise HTTPException(status_code=400, detail="Please upload a PDF, DOCX or TXT file")
    data = file.file.read()
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty")
    if len(data) > UPLOAD_MAX_BYTES:
        raise HTTPException(status_code=400, detail="File is too large (max 10 MB)")
    body = _normalize(extractor(data))
    if not body:
        raise HTTPException(
            status_code=400,
            detail="No readable text found in this file (scanned/image-only documents are not supported)")
    title = Path(filename).stem.strip()[:200] or "Untitled"
    a = models.KBArticle(type="general", title=title, content=body,
                         active=True, clinic_id=cid)
    db.add(a)
    db.commit()
    _reindex_async(cid)
    return article_dict(a)


@router.get("/overview")
def overview(db: Session = Depends(get_db), _u=Depends(current_user),
             cid: int = Depends(active_clinic_id)):
    chunks = scoped(db, models.KBChunk, cid).all()
    return {
        "articles": scoped(db, models.KBArticle, cid).count(),
        "services": scoped(db, models.Service, cid).count(),
        "promotions": scoped(db, models.Promotion, cid).count(),
        "chunks": len(chunks),
        "embedded": sum(1 for c in chunks if c.embedding),
    }


@router.post("/reindex")
def reindex(db: Session = Depends(get_db), _u=Depends(EDITOR),
            cid: int = Depends(active_clinic_id)):
    """Rebuild the vector index from this clinic's knowledge base sources."""
    return rag.reindex(db, clinic_id=cid)
