"""FastAPI 应用入口"""

import logging
import os
from datetime import datetime

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import Base, engine
from routers.auth import router as auth_router
from routers.diaries import router as diaries_router
from routers.tags import router as tags_router
from routers.dialogs import router as dialogs_router
from routers.admin_backup import router as admin_backup_router
from routers.transcriptions import router as transcriptions_router, file_router as transcription_files_router

# ---------------------------------------------------------------------------
# 全局日志配置 - 所有模块日志写入 app_YYYY-MM-DD.log
# ---------------------------------------------------------------------------
_log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(_log_dir, exist_ok=True)

_global_log_file = os.path.join(_log_dir, f"app_{datetime.now().strftime('%Y-%m-%d')}.log")
_file_handler = logging.FileHandler(_global_log_file, encoding="utf-8")
_file_handler.setLevel(logging.DEBUG)
_file_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
))

_console_handler = logging.StreamHandler()
_console_handler.setLevel(logging.INFO)
_console_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
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

# CORS 中间件（开发环境允许所有来源）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Access-Token"],
)

# 注册路由
api_router = APIRouter(prefix="/diary")
api_router.include_router(auth_router)
api_router.include_router(diaries_router)
api_router.include_router(tags_router)
api_router.include_router(dialogs_router)
api_router.include_router(admin_backup_router)
api_router.include_router(transcriptions_router)
api_router.include_router(transcription_files_router)
app.include_router(api_router)


@app.on_event("startup")
async def startup():
    """应用启动时创建数据库表"""
    _startup_logger.info("应用启动，初始化数据库...")
    # 导入所有模型，确保它们被注册到 Base.metadata
    import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    # 创建默认管理员账号
    _create_default_user()
    # 恢复服务器重启前卡死的整理任务
    _recover_stuck_tasks()
    from services.transcription_tasks import transcription_task_manager
    await transcription_task_manager.start()


@app.on_event("shutdown")
async def shutdown():
    from services.transcription_tasks import transcription_task_manager
    await transcription_task_manager.stop()


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


@app.get("/")
def root():
    """根路径健康检查"""
    return {"message": "日记管理平台 API", "docs": "/diary/docs"}


@app.get("/diary")
def diary_root():
    """日记平台后端入口健康检查"""
    return {"message": "日记管理平台 API", "docs": "/diary/docs"}
