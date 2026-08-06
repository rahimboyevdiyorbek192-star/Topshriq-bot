"""Avtonom kompyuter boshqaruv agenti (Ollama llava + pyautogui)."""
from .agent import ComputerAgent
from .screen import screenshot_bytes

__all__ = ["ComputerAgent", "screenshot_bytes"]
