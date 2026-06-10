"""Provider registry for the MoralMatrix module."""

from .heuristic import HeuristicMoralProvider
from .llama_cpp import LlamaCppMoralProvider
from .ollama import OllamaMoralProvider
from .openrouter import OpenRouterMoralProvider

__all__ = [
    "HeuristicMoralProvider",
    "LlamaCppMoralProvider",
    "OllamaMoralProvider",
    "OpenRouterMoralProvider",
]
