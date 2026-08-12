"""FastAPI 应用入口"""

import logging
import os
from datetime import datetime

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from database import Base, engine
from routers.auth import router as auth_router
from routers.diaries import router as diaries_router
from routers.tags import router as tags_router
from routers.dialogs import router as dialogs_router
from routers.admin_backup import router as admin_backup_router
from routers.admin_models import router as admin_models_router
from routers.admin_search import router as admin_search_router
from routers.transcriptions import router as transcriptions_router
from routers.schedules import router as schedules_router
from routers.voice_profile import router as voice_profile_router
from routers.reviews import router as reviews_router
from routers.actions import router as actions_router
from routers.knowledge import router as knowledge_router
from utils.log_context import ContextFormatter, LogContextFilter, log_extra, new_id, reset_request_context, set_request_context

# ---------------------------------------------------------------------------
# 全局日志配置 - 所有模块日志写入 app_YYYY-MM-DD.log
# ---------------------------------------------------------------------------
_log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(_log_dir, exist_ok=True)

_global_log_file = os.path.join(_log_dir, f"app_{datetime.now().strftime('%Y-%m-%d')}.log")
_file_handler = logging.FileHandler(_global_log_file, encoding="utf-8")
_file_handler.setLevel(logging.DEBUG)
_log_filter = LogContextFilter()
_log_format = (
    "%(asctime)s [%(name)s] %(levelname)s "
    "chain_id=%(chain_id)s request_id=%(request_id)s "
    "process=%(process)d thread=%(threadName)s/%(thread)d "
    "async_task=%(async_task)s event=%(event)s: %(message)s"
)
_file_handler.addFilter(_log_filter)
_file_handler.setFormatter(ContextFormatter(
    _log_format,
    defaults={"event": "-", "chain_id": "-", "request_id": "-", "async_task": "-"},
))

_console_handler = logging.StreamHandler()
_console_handler.setLevel(logging.INFO)
_console_handler.addFilter(_log_filter)
_console_handler.setFormatter(ContextFormatter(
    _log_format,
    defaults={"event": "-", "chain_id": "-", "request_id": "-", "async_task": "-"},
))

root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
root_logger.addHandler(_file_handler)
root_logger.addHandler(_console_handler)

_startup_logger = logging.getLogger("app.startup")

# 创建 FastAPI 应用
app = FastAPI(
    title="日记管理平台 API",
    description="个人日记管理平台后端服务",
    version="1.0.0",
    docs_url="/diary/docs",
    redoc_url="/diary/redoc",
    openapi_url="/diary/openapi.json",
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """为每个 HTTP 请求建立 request_id/chain_id 并记录请求闭环。"""
    request_id = request.headers.get("X-Request-ID") or new_id("req")
    chain_id = request.headers.get("X-Chain-ID") or request_id
    context_tokens = set_request_context(chain_id=chain_id, request_id=request_id)
    started_at = datetime.now()
    request_logger = logging.getLogger("http.request")
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    except Exception:
        request_logger.exception(
            "HTTP 请求未处理异常",
            extra=log_extra(
                event="http.request.failed",
                method=request.method,
                path=request.url.path,
                error_type="unhandled_exception",
            ),
        )
        raise
    finally:
        duration_ms = int((datetime.now() - started_at).total_seconds() * 1000)
        request_logger.info(
            "HTTP 请求完成",
            extra=log_extra(
                event="http.request.completed",
                method=request.method,
                path=request.url.path,
                status_code=status_code,
                duration_ms=duration_ms,
            ),
        )
        if "response" in locals():
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Chain-ID"] = chain_id
        reset_request_context(context_tokens)

# CORS 中间件（开发环境允许所有来源）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Access-Token", "X-Request-ID", "X-Chain-ID"],
)

# 注册路由
api_router = APIRouter(prefix="/diary")
api_router.include_router(auth_router)
api_router.include_router(diaries_router)
api_router.include_router(tags_router)
api_router.include_router(dialogs_router)
api_router.include_router(admin_backup_router)
api_router.include_router(admin_models_router)
api_router.include_router(admin_search_router)
api_router.include_router(transcriptions_router)
api_router.include_router(schedules_router)
api_router.include_router(voice_profile_router)
api_router.include_router(reviews_router)
api_router.include_router(actions_router)
api_router.include_router(knowledge_router)
app.include_router(api_router)


@app.on_event("startup")
async def startup():
    """应用启动时创建数据库表"""
    _startup_logger.info("应用启动，初始化数据库...")
    # 导入所有模型，确保它们被注册到 Base.metadata
    import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    # 初始化内置模型清单
    _seed_model_catalog()
    # 创建默认管理员账号
    _create_default_user()
    # 恢复服务器重启前卡死的整理任务
    _recover_stuck_tasks()
    from services.backup_scheduler import backup_scheduler
    await backup_scheduler.start()
    from services.schedule_occurrence_scheduler import schedule_occurrence_scheduler
    await schedule_occurrence_scheduler.start()
    from services.transcription_tasks import transcription_task_manager
    await transcription_task_manager.start()
    from services.review_tasks import review_task_manager
    await review_task_manager.start()
    from services.search_rebuild_jobs import search_index_rebuild_scheduler
    await search_index_rebuild_scheduler.start()
    from services.search_rebuild_jobs import search_index_maintenance_scheduler
    await search_index_maintenance_scheduler.start()
    from services.knowledge_tasks import knowledge_task_manager
    await knowledge_task_manager.start()


@app.on_event("shutdown")
async def shutdown():
    from services.knowledge_tasks import knowledge_task_manager
    await knowledge_task_manager.stop()
    from services.backup_scheduler import backup_scheduler
    await backup_scheduler.stop()
    from services.schedule_occurrence_scheduler import schedule_occurrence_scheduler
    await schedule_occurrence_scheduler.stop()
    from services.transcription_tasks import transcription_task_manager
    await transcription_task_manager.stop()
    from services.review_tasks import review_task_manager
    await review_task_manager.stop()
    from services.search_rebuild_jobs import search_index_rebuild_scheduler
    await search_index_rebuild_scheduler.stop()
    from services.search_rebuild_jobs import search_index_maintenance_scheduler
    await search_index_maintenance_scheduler.stop()


def _recover_stuck_tasks():
    """启动时将所有 running 状态的整理任务标记为 failed（服务器重启恢复）"""
    from database import SessionLocal
    from models.diary import OrganizeTask

    db = SessionLocal()
    try:
        stuck_tasks = db.query(OrganizeTask).filter(OrganizeTask.status == "running").all()
        for task in stuck_tasks:
            task.status = "failed"
            task.error_message = "服务器重启，整理任务已中断"
        if stuck_tasks:
            db.commit()
            _startup_logger.info("已恢复 %d 个中断的整理任务", len(stuck_tasks))
    finally:
        db.close()


def _create_default_user():
    """启动时创建默认管理员账号（admin / admin123），已存在则跳过"""
    # 局部导入，避免循环依赖
    from database import SessionLocal
    from models.user import User
    from utils.crypto import encrypt_password

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == "admin").first()
        if existing:
            _startup_logger.info("默认管理员账号已存在，跳过创建")
            return
        admin_user = User(
            username="admin",
            password_encrypted=encrypt_password("admin123"),
        )
        db.add(admin_user)
        db.commit()
        _startup_logger.info("默认管理员账号已创建: admin / admin123")
    finally:
        db.close()


def _seed_model_catalog():
    """启动时幂等初始化内置模型清单。"""
    from database import SessionLocal
    from services.model_seed import repair_model_management_schema, seed_model_catalog

    db = SessionLocal()
    try:
        repair_model_management_schema(db)
        seed_model_catalog(db)
    finally:
        db.close()


@app.get("/")
def root():
    """根路径健康检查"""
    return {"message": "日记管理平台 API", "docs": "/diary/docs"}


@app.get("/diary")
def diary_root():
    """日记平台后端入口健康检查"""
    return {"message": "日记管理平台 API", "docs": "/diary/docs"}
