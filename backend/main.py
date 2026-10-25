# main.py  - start the API:  python main.py
import uvicorn

if __name__ == "__main__":
    # Run as a SINGLE process (no --workers): the event queue, SSE broker and rate limiter live in memory.
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True, log_level="info")
