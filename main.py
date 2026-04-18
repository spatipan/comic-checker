from src.logging_config import configure_logging
from src.manga_checker import main as run_checker


def main():
    configure_logging()
    raise SystemExit(run_checker())


if __name__ == "__main__":
    main()
