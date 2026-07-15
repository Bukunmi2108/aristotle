from app.agent.capabilities.documents import DocumentTools
from app.agent.capabilities.local_web import LocalWebTools
from app.agent.capabilities.research import ResearchTools
from app.agent.capabilities.sandbox import SandboxTools
from app.agent.capabilities.utilities import UtilityTools

CUSTOM_CAPABILITY_TYPES = [
    LocalWebTools,
    ResearchTools,
    UtilityTools,
    DocumentTools,
    SandboxTools,
]

__all__ = [
    "CUSTOM_CAPABILITY_TYPES",
    "DocumentTools",
    "LocalWebTools",
    "ResearchTools",
    "SandboxTools",
    "UtilityTools",
]
