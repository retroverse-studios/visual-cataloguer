"""Visual Cataloguer - Batch catalogue physical collections using visual dividers."""

try:
    from importlib.metadata import version

    __version__ = version("visual-cataloguer")
except Exception:
    __version__ = "dev"
