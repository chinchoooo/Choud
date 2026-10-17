"""GET /api/search?q=... — names, plus the text inside documents once they are indexed."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.library import decorate
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas.files import ContentHit, SearchResponse
from app.services import file_service, index_service

router = APIRouter(prefix="/api", tags=["search"])


@router.get("/search", response_model=SearchResponse)
def search(
    q: str = Query(..., min_length=1, max_length=255),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    folders, files = file_service.search(db, current_user, q)
    hits = index_service.search_content(db, current_user, q, exclude={f.id for f in files})
    decorated = decorate(db, current_user, [file for file, _ in hits])
    content = [
        ContentHit(file=item, snippet=snippet)
        for item, (_, snippet) in zip(decorated, hits, strict=True)
    ]
    return SearchResponse(
        folders=folders, files=decorate(db, current_user, files), content=content
    )
