"""应用配置模块"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用配置，支持通过 .env 文件或环境变量覆盖"""

    # 数据库连接
    DATABASE_URL: str = "postgresql+psycopg://postgres:postgres@localhost:5432/diary_platform"

    # JWT 密钥
    SECRET_KEY: str = "L8qA6Gzbc1zb1iGw3CCgrTmzOyAWJR235dUOiQ0C7zk"

    # Fernet 对称加密密钥（生成方式: Fernet.generate_key()）
    ENCRYPTION_KEY: str = "qj4jBr6s9JAzeQao0P2_H8rMcL-CAEafVPt1Hwclh4c="

    # 系统备份包主密钥。生产环境必须通过环境变量覆盖。
    BACKUP_MASTER_KEY: str = "123456"

    # Fun-ASR 录音文件识别运行参数。模型、API 地址和密钥由管理端模型配置维护。
    TRANSCRIPTION_PUBLIC_BASE_URL: str = "http://localhost"
    TRANSCRIPTION_MAX_FILE_SIZE: int = 314572800
    TRANSCRIPTION_MAX_CONCURRENCY: int = 3
    TRANSCRIPTION_FAILED_RETENTION_DAYS: int = 7
    TRANSCRIPTION_DOWNLOAD_TOKEN_HOURS: int = 24
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_PUBLIC_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "diary_minio"
    MINIO_SECRET_KEY: str = "diary_minio_password"
    MINIO_BUCKET: str = "diary"
    MINIO_SECURE: bool = False
    MINIO_PUBLIC_SECURE: bool = False
    MINIO_UPLOAD_PREFIX: str = "transcriptions"

    @property
    def CHECKPOINT_CONN_STRING(self) -> str:
        """将 DATABASE_URL 的 postgresql+psycopg:// 替换为 postgresql://（AsyncPostgresSaver 需要纯 postgresql:// 格式）"""
        return self.DATABASE_URL.replace("postgresql+psycopg://", "postgresql://", 1)

    class Config:
        env_file = ".env"
        extra = "ignore"


# 全局配置实例
settings = Settings()
