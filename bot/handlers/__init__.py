"""Barcha routerlarni bitta joyda yig'ish."""
from aiogram import Router

from . import common, employees, reports, submissions, tasks


def setup_routers() -> Router:
    root = Router()
    # Tartib muhim: avval komandalar, keyin guruh xabarlari.
    root.include_router(common.router)
    root.include_router(employees.router)
    root.include_router(reports.router)
    root.include_router(tasks.router)
    root.include_router(submissions.router)
    return root
