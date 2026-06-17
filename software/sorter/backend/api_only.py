import os

import uvicorn

# The full runtime (main.py) initializes local state before importing the API.
# This standalone API-only entrypoint must do the same, otherwise every
# persisted-state read (recent known objects, sorting profiles, themes, …)
# comes back empty and the UI looks like a machine that has never run.
from local_state import initialize_local_state

initialize_local_state()

from server.api import app

if __name__ == "__main__":
    # Bind to loopback by default. Setting SORTER_API_HOST=0.0.0.0 (or a
    # specific IP) exposes the API to the LAN; see server/api.py for the CORS
    # trade-off.
    host = os.getenv("SORTER_API_HOST", "127.0.0.1") or "127.0.0.1"
    # log_config=None: skip uvicorn's dictConfig (unused here, and it can crash
    # the server at startup with "Unknown level: 'INFO'"). See main.py runServer.
    uvicorn.run(app, host=host, port=8000, log_level="error", log_config=None)
