"""Copy of ``worlds/metroidprime/DolphinClient.py`` (PLAN.md section J
deliverable 2), adapted so importing this module never requires
``dolphin_memory_engine`` to be installed.

Deviation from the Prime 1 file: Prime 1's ``DolphinClient.py`` imports
``dolphin_memory_engine`` at module level (``import dolphin_memory_engine``
as its very first import), which is NOT lazy -- importing that module (or
anything that imports it, e.g. ``MetroidPrimeInterface.py``) requires the
package to already be installed. Here the import is deferred into
``DolphinClient.__init__`` instead, so ``worlds.metroidprime2`` (and this
module) can be imported -- e.g. for Component/icon registration -- before
``utils.setup_libs()`` has had a chance to install the runtime
dependencies.
"""

from __future__ import annotations

import subprocess
from logging import Logger
from typing import Any

import Utils

GC_GAME_ID_ADDRESS = 0x80000000


class DolphinException(Exception):
    pass


class DolphinClient:
    logger: Logger

    def __init__(self, logger: Logger):
        import dolphin_memory_engine  # type: ignore

        self.dolphin = dolphin_memory_engine
        self.logger = logger

    def is_connected(self) -> bool:
        try:
            self.__assert_connected()
            return True
        except Exception:
            return False

    def connect(self) -> None:
        if not self.dolphin.is_hooked():
            self.dolphin.hook()
        if not self.dolphin.is_hooked():
            raise DolphinException(
                "Could not connect to Dolphin, verify that you have a game running in the emulator"
            )

    def disconnect(self) -> None:
        if self.dolphin.is_hooked():
            self.dolphin.un_hook()

    def __assert_connected(self) -> None:
        """Custom assert function that returns a DolphinException instead of a
        generic RuntimeError if the connection is lost"""
        try:
            self.dolphin.assert_hooked()
            # For some reason the dolphin_memory_engine.is_hooked() function doesn't recognize when the game is
            # closed, checking if memory is available will assert the connection is alive
            self.dolphin.read_bytes(GC_GAME_ID_ADDRESS, 1)
        except RuntimeError as e:
            self.disconnect()
            raise DolphinException(e) from e

    @staticmethod
    def verify_target_address(target_address: int, read_size: int) -> None:
        """Ensures that the target address is within the valid range for GC memory"""
        if target_address < 0x80000000 or target_address + read_size > 0x81800000:
            raise DolphinException(
                f"{target_address:x} -> {target_address + read_size:x} is not a valid for GC memory"
            )

    def read_pointer(self, pointer: int, offset: int, byte_count: int) -> Any:
        self.__assert_connected()

        try:
            address = self.dolphin.follow_pointers(pointer, [0])
        except RuntimeError:
            return None

        if not self.dolphin.is_hooked():
            raise DolphinException("Dolphin no longer connected")

        address += offset
        return self.read_address(address, byte_count)

    def read_address(self, address: int, bytes_to_read: int) -> Any:
        self.__assert_connected()
        DolphinClient.verify_target_address(address, bytes_to_read)
        return self.dolphin.read_bytes(address, bytes_to_read)

    def write_pointer(self, pointer: int, offset: int, data: Any) -> Any:
        self.__assert_connected()
        try:
            address = self.dolphin.follow_pointers(pointer, [0])
        except RuntimeError:
            return None

        if not self.dolphin.is_hooked():
            raise DolphinException("Dolphin no longer connected")

        address += offset
        return self.write_address(address, data)

    def write_address(self, address: int, data: Any) -> Any:
        self.__assert_connected()
        return self.dolphin.write_bytes(address, data)


def assert_no_running_dolphin() -> bool:
    """Only checks on windows for now, verifies no existing instances of dolphin are running."""
    if Utils.is_windows:
        if get_num_dolphin_instances() > 0:
            return False
    return True


def get_num_dolphin_instances() -> int:
    """Only checks on windows for now, kind of brittle so if it causes problems then just ignore it"""
    try:
        if Utils.is_windows:
            output = subprocess.check_output("tasklist", shell=True).decode()
            lines = output.strip().split("\n")
            return sum("Dolphin.exe" in line for line in lines)
        return 0
    except Exception:
        return 0
