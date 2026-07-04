"""PyInstaller entry script for the desktop build.

Kept outside the package so PyInstaller has a plain script to analyse;
all real logic lives in cataloguer.desktop.
"""

import multiprocessing

from cataloguer.desktop import main

if __name__ == "__main__":
    # Required for frozen builds on Windows/macOS: without it, any
    # multiprocessing child (spawned by libraries) re-runs the app.
    multiprocessing.freeze_support()
    main()
