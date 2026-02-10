import os


class GlobalConfig:
    db_path: str
    img_dir: str

    def __init__(self):
        pass


def mkGlobalConfig() -> GlobalConfig:
    gc = GlobalConfig()
    gc.db_path = os.environ["DB_PATH"]
    gc.img_dir = os.environ["IMG_DIR"]
    return gc
