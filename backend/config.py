"""应用配置模块"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用配置，支持通过 .env 文件或环境变量覆盖"""

    # 数据库连接
    DATABASE_URL: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/diary_platform"

    # JWT 密钥
    SECRET_KEY: str = "L8qA6Gzbc1zb1iGw3CCgrTmzOyAWJR235dUOiQ0C7zk"

    # Fernet 对称加密密钥（生成方式: Fernet.generate_key()）
    ENCRYPTION_KEY: str = "qj4jBr6s9JAzeQao0P2_H8rMcL-CAEafVPt1Hwclh4c="

    # DeepSeek API 配置（后续集成）
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_API_URL: str = "https://api.deepseek.com/v1"
    DEEPSEEK_MODEL: str = "deepseek-v4-flash"

    class Config:
        env_file = ".env"


# 全局配置实例
settings = Settings()
