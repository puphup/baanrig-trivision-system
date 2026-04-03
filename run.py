import uvicorn
from app.config import load_config

if __name__ == "__main__":
    cfg = load_config()
    host = cfg["server"]["host"]
    port = cfg["server"]["port"]
    uvicorn.run("app.server:app", host=host, port=port, reload=True)
