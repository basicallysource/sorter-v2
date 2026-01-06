from global_config import mkGlobalConfig


def main():
    gc = mkGlobalConfig()
    gc.logger.info("client starting...")


if __name__ == "__main__":
    main()
