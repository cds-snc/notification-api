########################
NESTED_VERSION = "1.0.0"
########################

try:
    from importlib.metadata import version
    __version__ = version("gcnotify")
except Exception:
    __version__ = NESTED_VERSION
