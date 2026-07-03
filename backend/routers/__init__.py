"""路由汇总导入"""

from routers.auth import router as auth_router
from routers.diaries import router as diaries_router
from routers.tags import router as tags_router
from routers.dialogs import router as dialogs_router

__all__ = ["auth_router", "diaries_router", "tags_router", "dialogs_router"]
