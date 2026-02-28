from pydantic_settings import BaseSettings
from pydantic import Field

class AppConfig(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}
    
    base_url: str = Field(default="http://localhost:8000", description="Hackapizza server base URL")
    api_key: str = Field(default="", description="x-api-key header value")
    restaurant_id: int = Field(default=1, description="Your restaurant ID")
    turn_id: int | None = Field(default=None, description="Current turn_id")
    
    http_timeout_s: float = 10.0
    max_concurrency: int = 5
    polling_mode: str = "normal"  # "low" | "normal" | "aggressive"
    
    sqlite_path: str = "hackapizza_dashboard.sqlite"
    persistence_enabled: bool = True
    persistence_flush_interval_s: float = 5.0

    # MySQL bridge (reads events written by main.py)
    mysql_enabled: bool = True
    mysql_host: str = Field(default="127.0.0.1")
    mysql_port: int = Field(default=3306)
    mysql_user: str = Field(default="appuser")
    mysql_password: str = Field(default="apppassword")
    mysql_db: str = Field(default="hackapizza")
    mysql_poll_interval_s: float = Field(default=1.0)
    
    ui_host: str = "0.0.0.0"
    ui_port: int = 8080
