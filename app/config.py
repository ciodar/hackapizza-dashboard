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
    
    ui_host: str = "0.0.0.0"
    ui_port: int = 8080
