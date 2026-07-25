from app.agent.capabilities.documents import DocumentTools
from app.agent.capabilities.local_web import LocalWebTools
from app.agent.capabilities.research import ResearchTools
from app.agent.capabilities.utilities import UtilityTools
from app.agent.capabilities.workspace import WorkspaceTools

CUSTOM_CAPABILITY_TYPES = [
    LocalWebTools,
    ResearchTools,
    UtilityTools,
    DocumentTools,
    WorkspaceTools,
]

__all__ = [
    "CUSTOM_CAPABILITY_TYPES",
    "DocumentTools",
    "LocalWebTools",
    "ResearchTools",
    "UtilityTools",
    "WorkspaceTools",
]
