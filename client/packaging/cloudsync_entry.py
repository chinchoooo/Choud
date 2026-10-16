"""Entry point for the frozen (PyInstaller) Windows build: `cloudsync.exe`.

PyInstaller needs a plain script to start from; this just runs the same `main()` as the
`cloudsync` console command. Build with `packaging/build_windows.ps1` (or see client/README.md).
"""

import sys

from cloudsync.main import main

if __name__ == "__main__":
    sys.exit(main())
