from fastapi import APIRouter

from web.api.routes.anime import covers, files, library, scraping, updates

router = APIRouter()
router.include_router(scraping.router)
router.include_router(library.router)
router.include_router(updates.router)
router.include_router(files.router)
router.include_router(covers.router)

__all__ = ["router"]
