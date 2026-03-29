"""Platform name normalisation for retro gaming consoles and handhelds.

Maps common synonyms/abbreviations to a single canonical name.
Unknown platforms pass through unchanged.
"""

# Canonical name -> list of synonyms (case-insensitive matching)
_PLATFORM_ALIASES: dict[str, list[str]] = {
    # Nintendo home consoles
    "NES": [
        "Nintendo Entertainment System",
        "Famicom",
        "Nintendo Famicom",
        "Family Computer",
        "FC",
    ],
    "SNES": [
        "Super Nintendo",
        "Super Nintendo Entertainment System",
        "Super NES",
        "Super Famicom",
        "SFC",
    ],
    "N64": [
        "Nintendo 64",
        "Nintendo64",
    ],
    "GameCube": [
        "Nintendo GameCube",
        "NGC",
        "GCN",
    ],
    "Wii": [
        "Nintendo Wii",
    ],
    "Wii U": [
        "Nintendo Wii U",
        "WiiU",
    ],
    "Switch": [
        "Nintendo Switch",
    ],
    # Nintendo handhelds
    "Game Boy": [
        "Nintendo Game Boy",
        "GameBoy",
        "GB",
    ],
    "Game Boy Color": [
        "Nintendo Game Boy Color",
        "GameBoy Color",
        "GBC",
        "Game Boy Colour",
        "GameBoy Colour",
    ],
    "Game Boy Advance": [
        "Nintendo Game Boy Advance",
        "GameBoy Advance",
        "GBA",
    ],
    "DS": [
        "Nintendo DS",
        "NDS",
    ],
    "3DS": [
        "Nintendo 3DS",
        "N3DS",
    ],
    "Game & Watch": [
        "Game and Watch",
        "Nintendo Game & Watch",
        "Nintendo Game and Watch",
    ],
    # Sony
    "PS1": [
        "PlayStation",
        "PlayStation 1",
        "Playstation",
        "Playstation 1",
        "PSX",
        "PS One",
        "PSOne",
        "Sony PlayStation",
        "Sony Playstation",
    ],
    "PS2": [
        "PlayStation 2",
        "Playstation 2",
        "Sony PlayStation 2",
        "Sony Playstation 2",
    ],
    "PS3": [
        "PlayStation 3",
        "Playstation 3",
        "Sony PlayStation 3",
        "Sony Playstation 3",
    ],
    "PS4": [
        "PlayStation 4",
        "Playstation 4",
        "Sony PlayStation 4",
        "Sony Playstation 4",
    ],
    "PS5": [
        "PlayStation 5",
        "Playstation 5",
        "Sony PlayStation 5",
        "Sony Playstation 5",
    ],
    "PSP": [
        "PlayStation Portable",
        "Playstation Portable",
        "Sony PSP",
    ],
    "PS Vita": [
        "PlayStation Vita",
        "Playstation Vita",
        "PSVita",
        "Vita",
        "Sony PS Vita",
    ],
    # Sega
    "Master System": [
        "Sega Master System",
        "SMS",
    ],
    "Mega Drive": [
        "Sega Mega Drive",
        "Genesis",
        "Sega Genesis",
    ],
    "Game Gear": [
        "Sega Game Gear",
        "GameGear",
        "GG",
    ],
    "Saturn": [
        "Sega Saturn",
    ],
    "Dreamcast": [
        "Sega Dreamcast",
        "DC",
    ],
    "Sega CD": [
        "Mega CD",
        "Sega Mega CD",
        "Mega-CD",
    ],
    "32X": [
        "Sega 32X",
        "Sega Genesis 32X",
        "Mega Drive 32X",
    ],
    # Atari
    "Atari 2600": [
        "Atari VCS",
        "VCS",
        "Atari Video Computer System",
    ],
    "Atari 5200": [],
    "Atari 7800": [],
    "Atari Jaguar": [
        "Jaguar",
    ],
    "Atari Lynx": [
        "Lynx",
    ],
    # Other
    "Neo Geo": [
        "NeoGeo",
        "Neo-Geo",
        "SNK Neo Geo",
        "Neo Geo AES",
        "Neo Geo MVS",
    ],
    "Neo Geo Pocket": [
        "Neo Geo Pocket Color",
        "NGP",
        "NGPC",
        "NeoGeo Pocket",
    ],
    "TurboGrafx-16": [
        "TurboGrafx 16",
        "PC Engine",
        "TG-16",
        "TG16",
    ],
    "3DO": [
        "3DO Interactive Multiplayer",
        "Panasonic 3DO",
    ],
    "Intellivision": [
        "Mattel Intellivision",
    ],
    "ColecoVision": [
        "Coleco Vision",
    ],
    "Vectrex": [],
    "WonderSwan": [
        "WonderSwan Color",
        "Wonder Swan",
        "Bandai WonderSwan",
    ],
    # Microsoft
    "Xbox": [
        "Microsoft Xbox",
        "Xbox Original",
    ],
    "Xbox 360": [
        "Microsoft Xbox 360",
        "X360",
    ],
    "Xbox One": [
        "Microsoft Xbox One",
        "XB1",
        "Xbone",
    ],
    "Xbox Series X": [
        "Xbox Series X/S",
        "Xbox Series S",
        "XSX",
    ],
    # Computers (common retro)
    "ZX Spectrum": [
        "Sinclair ZX Spectrum",
        "Spectrum",
    ],
    "Commodore 64": [
        "C64",
    ],
    "Amiga": [
        "Commodore Amiga",
    ],
    "Amstrad CPC": [
        "CPC",
        "Amstrad",
    ],
}

# Build the reverse lookup: lowercased synonym -> canonical name
_LOOKUP: dict[str, str] = {}
for _canonical, _aliases in _PLATFORM_ALIASES.items():
    _key = _canonical.lower()
    _LOOKUP[_key] = _canonical
    for _alias in _aliases:
        _LOOKUP[_alias.lower()] = _canonical


def normalise_platform(name: str | None) -> str | None:
    """Normalise a platform name to its canonical form.

    Returns the canonical name if a match is found, otherwise
    returns the original name unchanged.
    """
    if not name:
        return name
    return _LOOKUP.get(name.strip().lower(), name.strip())


def get_canonical_platforms() -> list[str]:
    """Return sorted list of all canonical platform names."""
    return sorted(_PLATFORM_ALIASES.keys())
