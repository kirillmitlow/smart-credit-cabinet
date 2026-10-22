"""Оркестрация конвейера: сбор данных, снимки, вызов decide(), переход по результату. Документ: 30-01, 50-05."""

from app.modules.pipeline.policy_loader import load_policy_file

__all__ = ["load_policy_file"]
