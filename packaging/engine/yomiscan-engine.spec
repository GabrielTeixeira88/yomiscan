# PyInstaller spec for the Torch-free local engine (Stage 5b). Built by scripts/build_engine.py,
# which runs it in an environment without the PyTorch `reference` group.
# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules, copy_metadata

ENTRY = os.environ["YOMISCAN_ENGINE_ENTRY"]
EXCLUDED = os.environ["YOMISCAN_ENGINE_EXCLUDED"].split(",")

analysis = Analysis(
    [ENTRY],
    binaries=collect_dynamic_libs("fugashi"),
    datas=[*copy_metadata("yomiscan"), *collect_data_files("yomiscan"), *collect_data_files("unidic_lite")],
    hiddenimports=[*collect_submodules("uvicorn"), *collect_submodules("yomiscan")],
    excludes=EXCLUDED,
    # The processing cache keys results by a hash of the analysis source files
    # (cache_identity.algorithm), so YomiScan's own .py files ship next to the bytecode.
    module_collection_mode={"yomiscan": "pyz+py"},
    noarchive=False,
)
pyz = PYZ(analysis.pure)
# Two executables share one folder: the console one for commands (--prepare, --register, --version)
# and a windowless one that Chrome starts as the native-messaging host and that runs the detached
# engine, so no console window appears.
exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name="yomiscan-engine", console=True,
          debug=False, strip=False, upx=False)
# disable_windowed_traceback: an unhandled error must end the process (its traceback goes to the
# log file that the launcher attaches), never open a dialog that waits invisibly for a click.
host = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name="yomiscan-engine-host", console=False,
           disable_windowed_traceback=True, debug=False, strip=False, upx=False)
coll = COLLECT(exe, host, analysis.binaries, analysis.datas, strip=False, upx=False, name="yomiscan-engine")
