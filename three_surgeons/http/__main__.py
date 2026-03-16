"""Allow running: python -m three_surgeons.http"""
import os

from three_surgeons.http.server import create_app

if __name__ == "__main__":
    import uvicorn
    app = create_app()
    port = int(os.environ.get("PORT", "3456"))
    uvicorn.run(app, host="127.0.0.1", port=port)
