# import uvicorn

# if __name__ == "__main__":
#     uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)



# start.py
from app.main import app
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",  # Explicitly use localhost
        port=8000,
        reload=True,
        log_level="debug"  # Get more detailed logs
    )