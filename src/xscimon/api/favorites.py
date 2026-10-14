from fastapi import APIRouter, Depends
from sqlmodel import Session
from ..database import get_session
from ..repositories import FavoriteRepo

router = APIRouter(prefix="/api/favorites", tags=["favorites"])


@router.get("")
def list_favorites(session: Session = Depends(get_session)):
    return {"post_ids": FavoriteRepo(session).get_all_ids()}


@router.post("/{post_id}", status_code=201)
def star_post(post_id: str, session: Session = Depends(get_session)):
    FavoriteRepo(session).star(post_id)
    return {"post_id": post_id, "starred": True}


@router.delete("/{post_id}", status_code=204)
def unstar_post(post_id: str, session: Session = Depends(get_session)):
    FavoriteRepo(session).unstar(post_id)
