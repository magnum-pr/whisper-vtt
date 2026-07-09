"""PyInstaller runtime hook: pre-load native DLLs before imports.

Windows only -- no-op on macOS and other platforms.
"""

import sys

if sys.platform != "win32":
    pass  # no-op on non-Windows
else:
    import os
    import ctypes
    from pathlib import Path

    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent / "_internal"
        kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)

        for d in [base, base / "torch" / "lib"]:
            try:
                os.add_dll_directory(str(d))
            except OSError:
                pass

        for dll_name in ["vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll"]:
            dll_path = base / dll_name
            if dll_path.exists():
                kernel32.LoadLibraryW(str(dll_path))
