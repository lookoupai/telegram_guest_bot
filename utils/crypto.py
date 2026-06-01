from __future__ import annotations

from cryptography.fernet import Fernet


class TokenCipher:
    """Bot Token 加密工具。

    数据库只保存 Fernet 密文；运行时需要使用同一个 FERNET_KEY 解密。
    """

    def __init__(self, fernet_key: str) -> None:
        self._fernet = Fernet(fernet_key.encode("utf-8"))

    def encrypt(self, token: str) -> str:
        """加密 Bot Token。"""

        return self._fernet.encrypt(token.encode("utf-8")).decode("utf-8")

    def decrypt(self, encrypted_token: str) -> str:
        """解密 Bot Token。"""

        return self._fernet.decrypt(encrypted_token.encode("utf-8")).decode("utf-8")
