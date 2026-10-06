"""运行配置。

所有值来自环境变量或 .env 文件，作为前端未传入配置时的默认值。
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from .paths import env_file, resolve_data_dir


class Settings(BaseSettings):
    # env_file 走绝对路径：相对路径会被 pydantic-settings 按 cwd 解析，
    # 于是 `python -m app` 和 `uvicorn --reload` 可能读到不同的 .env。
    model_config = SettingsConfigDict(
        env_file=str(env_file()), env_file_encoding="utf-8", extra="ignore"
    )

    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_temperature: float = 0.2

    # 绝对路径。默认 %APPDATA%\Weister\data；DATA_DIR 环境变量优先。
    data_dir: str = str(resolve_data_dir())
    # 桌面客户端启动时由 Electron 传入真实端口覆盖此默认值；
    # 默认值只服务纯浏览器开发模式（next dev 跑在 3000）。
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # 联网搜索源（tools/web.py 按此顺序降级：tavily → bocha → searxng → bing_cn）
    tavily_api_key: str = ""
    bocha_api_key: str = ""
    searxng_url: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def runs_dir(self) -> str:
        """聊天形态的 messages.jsonl 落盘目录。

        与 storage.DATA_DIR 同源（都是 ./data），但用单独子目录区分文件类型：
            ./data/checkpoints/  ← 流水线形态检查点（单 JSON）
            ./data/runs/<id>/    ← 聊天形态 messages（每 run 一个目录，多文件可扩展）
        """
        return str(Path(self.data_dir) / "runs")

    @property
    def runs_dir_path(self) -> Path:
        return Path(self.runs_dir).resolve()


settings = Settings()
