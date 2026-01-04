from datetime import datetime

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from sqlalchemy import desc, select

from ..infrastructure.database import AsyncSessionLocal
from ..infrastructure.models import ChatMessage


class HistoryService:
    @staticmethod
    async def save_message(
        thread_id: str, message: BaseMessage, role: str | None = None
    ):
        if role is None:
            if isinstance(message, HumanMessage):
                role = "user"
            elif isinstance(message, AIMessage):
                role = "assistant"
            elif isinstance(message, ToolMessage):
                role = "tool"
            else:
                role = "system"

        # Extract metadata
        metadata = getattr(message, "additional_kwargs", {}).copy()
        if hasattr(message, "response_metadata"):
            metadata.update(message.response_metadata)

        # Ensure we have a type and potentially data for structured messages
        if "type" not in metadata:
            metadata["type"] = "text"

        async with AsyncSessionLocal() as session:
            db_message = ChatMessage(
                thread_id=thread_id,
                role=role,
                content=message.content,
                message_type=message.type,
                metadata_=metadata,
            )
            session.add(db_message)
            await session.commit()
            return db_message

    @staticmethod
    async def get_history(
        thread_id: str, limit: int = 20, before: datetime | None = None
    ) -> list[ChatMessage]:
        async with AsyncSessionLocal() as session:
            query = select(ChatMessage).where(ChatMessage.thread_id == thread_id)

            if before:
                query = query.where(ChatMessage.created_at < before)

            query = query.order_by(desc(ChatMessage.created_at)).limit(limit)

            result = await session.execute(query)
            # Reverse because we want chronological order for the frontend
            messages = list(result.scalars().all())
            messages.reverse()
            return messages


history_service = HistoryService()
