"""密码加密/解密工具

使用 cryptography 库的 Fernet 对称加密方案。
生产环境务必在 .env 中配置 ENCRYPTION_KEY（通过 Fernet.generate_key() 生成）。
"""

import warnings

from cryptography.fernet import Fernet

from config import settings

# 模块级缓存 Fernet 实例，避免重复创建
_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    """获取 Fernet 实例（惰性初始化并缓存）"""
    global _fernet
    if _fernet is None:
        key = settings.ENCRYPTION_KEY
        if not key:
            # 开发环境：自动生成随机密钥（重启后无法解密旧数据，仅限开发使用）
            warnings.warn(
                "ENCRYPTION_KEY 未配置，使用随机生成的密钥。"
                "生产环境必须通过 Fernet.generate_key() 生成并配置 ENCRYPTION_KEY！"
            )
            key = Fernet.generate_key().decode()
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def encrypt_password(password: str) -> str:
    """加密明文密码，返回密文字符串"""
    f = _get_fernet()
    return f.encrypt(password.encode("utf-8")).decode("utf-8")


def decrypt_password(encrypted: str) -> str:
    """解密密文密码，返回明文字符串"""
    f = _get_fernet()
    return f.decrypt(encrypted.encode("utf-8")).decode("utf-8")


def verify_password(password: str, encrypted: str) -> bool:
    """验证明文密码与密文是否匹配"""
    try:
        return decrypt_password(encrypted) == password
    except Exception:
        return False
