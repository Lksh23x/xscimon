from fastapi import APIRouter
from .domains import router as domains_router
from .digest import router as digest_router
from .keywords import router as keywords_router
from .admin import router as admin_router
from .email import router as email_router
from .favorites import router as favorites_router

api_router = APIRouter()
api_router.include_router(domains_router)
api_router.include_router(digest_router)
api_router.include_router(keywords_router)
api_router.include_router(admin_router)
api_router.include_router(email_router)
api_router.include_router(favorites_router)
