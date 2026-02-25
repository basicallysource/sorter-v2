import uvicorn
from global_config import mkGlobalConfig
from parts_cache import loadPartsCache, SyncManager
from server import mkApp


def main():
    gc = mkGlobalConfig()
    cache = loadPartsCache(gc)
    sync = SyncManager()
    app = mkApp(gc, cache, sync)
    uvicorn.run(app, host="0.0.0.0", port=gc.port)


if __name__ == "__main__":
    main()
