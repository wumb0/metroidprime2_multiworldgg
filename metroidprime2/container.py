"""Player output container for Metroid Prime 2: Echoes (``.apmp2``).

Mirrors ``worlds/metroidprime/Container.py``'s ``MetroidPrimeContainer``
(minus the PPC hook-assembly helpers, which are Prime 1-specific): a
zipfile with ``config.json`` (the OPR ``RandoConfiguration`` produced by
``patch_data.make_rando_configuration``) and ``options.json`` (small
client-side metadata) alongside the standard AP manifest. See PLAN.md
section I.
"""

from __future__ import annotations

import os
import zipfile

from worlds.Files import APPlayerContainer

from . import constants


class MetroidPrime2Container(APPlayerContainer):
    game: str = constants.GAME_NAME
    patch_file_ending = ".apmp2"

    def __init__(
        self,
        config_json: str,
        options_json: str,
        outfile_name: str,
        output_directory: str,
        player: int | None = None,
        player_name: str = "",
        server: str = "",
    ) -> None:
        self.config_json = config_json
        self.config_path = "config.json"
        self.options_path = "options.json"
        self.options_json = options_json
        container_path = os.path.join(output_directory, f"{outfile_name}{self.patch_file_ending}")
        super().__init__(container_path, player, player_name, server)

    def write_contents(self, opened_zipfile: zipfile.ZipFile) -> None:
        opened_zipfile.writestr(self.config_path, self.config_json)
        opened_zipfile.writestr(self.options_path, self.options_json)
        super().write_contents(opened_zipfile)
