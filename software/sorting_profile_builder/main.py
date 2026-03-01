import uvicorn
from global_config import mkGlobalConfig
from db import initDb, PartsData, reloadPartsData
from parts_cache import SyncManager
from server import mkApp


def main():
    gc = mkGlobalConfig()
    conn = initDb(gc.db_path)
    parts_data = PartsData()
    reloadPartsData(conn, parts_data)
    sync = SyncManager()
    app = mkApp(gc, conn, parts_data, sync)
    uvicorn.run(app, host="0.0.0.0", port=gc.port)


if __name__ == "__main__":
    main()
