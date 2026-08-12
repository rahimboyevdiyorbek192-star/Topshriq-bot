"""Barcha routerlarni bitta joyda yig'ish."""
from aiogram import Router

from . import ai_handler, buttons, common, employees, location, reports, submissions, tasks


def setup_routers() -> Router:
    root = Router()
    root.include_router(common.router)
    root.include_router(buttons.router)
    root.include_router(ai_handler.router)
    root.include_router(employees.router)
    root.include_router(reports.router)
    root.include_router(tasks.router)        # kanal + guruh topshiriqlar
    root.include_router(submissions.router)  # guruh + DM submission
    root.include_router(location.router)     # jonli lokatsiya
    return root
