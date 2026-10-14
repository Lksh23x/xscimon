from sqlmodel import Session, select
from ..models import FavoritePost


class FavoriteRepo:
    def __init__(self, session: Session):
        self._s = session

    def star(self, post_id: str) -> None:
        if not self._s.get(FavoritePost, post_id):
            self._s.add(FavoritePost(post_id=post_id))
            self._s.commit()

    def unstar(self, post_id: str) -> None:
        fav = self._s.get(FavoritePost, post_id)
        if fav:
            self._s.delete(fav)
            self._s.commit()

    def get_all_ids(self) -> list[str]:
        return [f.post_id for f in self._s.exec(select(FavoritePost)).all()]
