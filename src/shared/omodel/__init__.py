"""Rugby 08 model/texture readers (.o models, .fsh textures, .big archives)."""
from .bigfile import BigArchive
from .fshlib import Fsh
from .olib import parse_o
from .player_model import (
    PlayerAssets, PlayerModel, Part, load_player, variants_from_kit_config,
)

__all__ = ["BigArchive", "Fsh", "parse_o",
           "PlayerAssets", "PlayerModel", "Part", "load_player",
           "variants_from_kit_config"]
