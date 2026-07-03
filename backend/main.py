"""FastAPI 应用入口"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import Base, engine
from routers.auth import router as auth_router
from routers.diaries import router as diaries_router
from routers.tags import router as tags_router
from routers.dialogs import router as dialogs_router

# 创建 FastAPI 应用
app = FastAPI(
    title="日记管理平台 API",
    description="个人日记管理平台后端服务",
    version="1.0.0",
)

# CORS 中间件（开发环境允许所有来源）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(auth_router)
app.include_router(diaries_router)
app.include_router(tags_router)
app.include_router(dialogs_router)


@app.on_event("startup")
def startup():
    """应用启动时创建数据库表"""
    # 导入所有模型，确保它们被注册到 Base.metadata
    import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    # 创建默认管理员账号
    _create_default_user()
    # 恢复服务器重启前卡死的整理任务
    _recover_stuck_tasks()


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
            print(f"已恢复 {len(stuck_tasks)} 个中断的整理任务")
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
            print("默认管理员账号已存在，跳过创建")
            return
        admin_user = User(
            username="admin",
            password_encrypted=encrypt_password("admin123"),
        )
        db.add(admin_user)
        db.commit()
        print("默认管理员账号已创建: admin / admin123")
    finally:
        db.close()


@app.get("/")
def root():
    """根路径健康检查"""
    return {"message": "日记管理平台 API", "docs": "/docs"}
