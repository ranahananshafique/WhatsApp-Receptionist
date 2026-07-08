"""
Convenience entry-point so you can run the server with:

    python run.py

Instead of the longer uvicorn CLI.
"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
