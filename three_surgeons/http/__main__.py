"""Allow running: python -m three_surgeons.http"""
from three_surgeons.http.server import create_app

if __name__ == "__main__":
    import uvicorn
    app = create_app()
    uvicorn.run(app, host="127.0.0.1", port=3456)
