from app.agent.capabilities.local_web import LocalWebTools
from app.agent.capabilities.utilities import UtilityTools

CUSTOM_CAPABILITY_TYPES = [LocalWebTools, UtilityTools]

__all__ = ["CUSTOM_CAPABILITY_TYPES", "LocalWebTools", "UtilityTools"]
