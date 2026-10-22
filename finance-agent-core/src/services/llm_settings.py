"""Application-owned persistence for the selected LLM model policy."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from src.infrastructure.database import AsyncSessionLocal
from src.infrastructure.models import LlmSetting

SETTING_ID = "selected_model"
DEFAULT_SELECTED_MODEL = "openrouter/free"


async def get_selected_model() -> str:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(LlmSetting).where(LlmSetting.id == SETTING_ID)
        )
        setting = result.scalar_one_or_none()
        return setting.value if setting is not None else DEFAULT_SELECTED_MODEL


async def set_selected_model(model_id: str, *, updated_by: str) -> str:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(LlmSetting).where(LlmSetting.id == SETTING_ID)
        )
        setting = result.scalar_one_or_none()
        # Existing application tables use PostgreSQL TIMESTAMP WITHOUT TIME ZONE.
        now = datetime.utcnow()
        if setting is None:
            setting = LlmSetting(
                id=SETTING_ID, value=model_id, updated_at=now, updated_by=updated_by
            )
            session.add(setting)
        else:
            setting.value = model_id
            setting.updated_at = now
            setting.updated_by = updated_by
        await session.commit()
        return model_id
