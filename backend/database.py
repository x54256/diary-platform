"""数据库连接与会话管理"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from config import settings

# 创建数据库引擎，pool_pre_ping 确保连接有效
engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)

# 会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 声明式基类，所有模型继承此类
Base = declarative_base()


def get_db():
    """数据库会话依赖，用于 FastAPI 依赖注入"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
