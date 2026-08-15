from app.agent.capabilities.documents import DocumentTools
from app.agent.capabilities.local_web import LocalWebTools
from app.agent.capabilities.memory import MemoryTools
from app.agent.capabilities.replay_safe import ReplaySafeTools
from app.agent.capabilities.research import ResearchTools
from app.agent.capabilities.utilities import UtilityTools
from app.agent.capabilities.workspace import WorkspaceTools

CUSTOM_CAPABILITY_TYPES = [
    LocalWebTools,
    ResearchTools,
    UtilityTools,
    DocumentTools,
    WorkspaceTools,
    MemoryTools,
    ReplaySafeTools,
]

__all__ = [
    "CUSTOM_CAPABILITY_TYPES",
    "DocumentTools",
    "LocalWebTools",
    "MemoryTools",
    "ReplaySafeTools",
    "ResearchTools",
    "UtilityTools",
    "WorkspaceTools",
]
