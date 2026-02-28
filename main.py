from app.main import create_app
import uvicorn

app = create_app()

if __name__ == "__main__":
    from app.config import AppConfig
    cfg = AppConfig()
    uvicorn.run("main:app", host=cfg.ui_host, port=cfg.ui_port, reload=False)
