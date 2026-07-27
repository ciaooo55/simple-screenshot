import multiprocessing


if __name__ == "__main__":
    multiprocessing.freeze_support()
    from simple_screenshot.app import run

    raise SystemExit(run())
