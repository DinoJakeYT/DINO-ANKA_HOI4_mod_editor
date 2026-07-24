"""ANKA — Hearts of Iron IV mod editor. Entry point."""
from anka.app import AnkaApp


def main() -> None:
    try:
        AnkaApp().run()
    except KeyboardInterrupt:
        # Closing a console-launched GUI with Ctrl+C is a normal exit, not an
        # ANKA crash; avoid presenting users with a misleading traceback.
        pass


if __name__ == "__main__":
    main()
