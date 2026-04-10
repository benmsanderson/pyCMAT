"""
pyCMAT source package.
"""
from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("pycmat")
except PackageNotFoundError:
    __version__ = "dev"
