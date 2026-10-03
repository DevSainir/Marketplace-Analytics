"""Public contract of the ``advertising`` module.

Nothing consumes it yet; it exists because every module has exactly one door,
and the response and the service are what a future caller would need.
"""

from src.modules.advertising.schemas import AdvertisingResponse, AdvertisingSpan
from src.modules.advertising.services import AdvertisingService

__all__ = ["AdvertisingResponse", "AdvertisingService", "AdvertisingSpan"]
