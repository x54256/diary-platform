"""应用配置模块"""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """应用配置，支持通过 .env 文件或环境变量覆盖"""

    # 数据库连接
    DATABASE_URL: str = "postgresql+psycopg://postgres:postgres@localhost:5432/diary_platform"
    # 任务队列环境标识。共享数据库时必须为本地、测试、生产设置不同值。
    APP_ENV: str = "local"

    # Skill 固定 Token；留空时关闭接口。仅允许访问绑定用户。
    SKILL_API_TOKEN: str = ""
    SKILL_API_USERNAME: str = "x5456"

    # JWT 密钥
    SECRET_KEY: str = "L8qA6Gzbc1zb1iGw3CCgrTmzOyAWJR235dUOiQ0C7zk"

    # Fernet 对称加密密钥（生成方式: Fernet.generate_key()）
    ENCRYPTION_KEY: str = "qj4jBr6s9JAzeQao0P2_H8rMcL-CAEafVPt1Hwclh4c="

    # 系统备份包主密钥。生产环境必须通过环境变量覆盖。
    BACKUP_MASTER_KEY: str = "123456"
    # 定时备份配置。时间格式为 HH:MM，时区使用 IANA 时区名称。
    BACKUP_STORAGE_PATH: str = "backup_packages"
    BACKUP_SCHEDULE_TIME: str = "02:00"
    BACKUP_SCHEDULE_TIMEZONE: str = "Asia/Shanghai"

    # 大模型单个业务步骤的最大总调用次数；1 表示失败后不自动重试。
    LLM_MAX_ATTEMPTS: int = Field(default=1, ge=1)
    # 每日回顾素材单批请求的输入 token 上限；完整事件不可拆分。
    REVIEW_DAILY_MATERIAL_INPUT_TOKEN_BUDGET: int = Field(default=24000, ge=1024)

    # 事件图谱请求预算；随任务冻结，可按实际渠道容量配置。
    GRAPH_CONTEXT_TOKEN_LIMIT: int = Field(default=65536, ge=4096)
    GRAPH_MAX_OUTPUT_TOKENS: int = Field(default=16384, ge=1024)
    GRAPH_OUTPUT_TOKENS_PER_PAIR: int = Field(default=512, ge=128)
    GRAPH_CONTEXT_SAFETY_TOKENS: int = Field(default=2048, ge=0)
    GRAPH_EMBEDDING_MAX_CHARS: int = Field(default=8000, ge=128)
    GRAPH_RECALL_MIN_SIMILARITY: float = Field(default=0.4, ge=0, le=1)
    GRAPH_RECALL_TOP_K: int = Field(default=5, ge=1)
    GRAPH_LEASE_SECONDS: int = Field(default=180, ge=60)
    GRAPH_HEARTBEAT_SECONDS: int = Field(default=30, ge=5)

    # Fun-ASR 录音文件识别运行参数。模型、API 地址和密钥由管理端模型配置维护。
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
