from datetime import datetime

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from sqlalchemy import desc, select

from ..infrastructure.database import AsyncSessionLocal
from ..infrastructure.models import ChatMessage


class HistoryService:
    @staticmethod
    async def save_messages(
        thread_id: str, messages: list[BaseMessage]
    ) -> list[ChatMessage]:
        """Saves a list of messages to the database in a single transaction."""
        db_messages = []
        for message in messages:
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

            # Sanitize metadata to ensure JSON serializability (handle Pydantic models, etc.)
            metadata = HistoryService._sanitize_obj(metadata)

            db_messages.append(
                ChatMessage(
                    thread_id=thread_id,
                    role=role,
                    content=message.content,
                    message_type=message.type,
                    metadata_=metadata,
                )
            )

        async with AsyncSessionLocal() as session:
            session.add_all(db_messages)
            await session.commit()
            # Refresh the instances to load the latest data from the DB (e.g. created_at, id)
            # before the session closes.
            for msg in db_messages:
                await session.refresh(msg)
            return db_messages

    @staticmethod
    async def save_message(
        thread_id: str, message: BaseMessage, role: str | None = None
    ):
        """Saves a single message, using the batch method for efficiency."""
        # If a role is explicitly provided, handle it as a special case
        # Otherwise, delegate to the batch-saving method
        if role:
            metadata = getattr(message, "additional_kwargs", {}).copy()
            if hasattr(message, "response_metadata"):
                metadata.update(message.response_metadata)
            if "type" not in metadata:
                metadata["type"] = "text"
            metadata = HistoryService._sanitize_obj(metadata)

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
        else:
            # Default case: use the batch method for a single message
            results = await HistoryService.save_messages(thread_id, [message])
            return results[0]

    @staticmethod
    def _sanitize_obj(obj):
        """Recursively convert objects to JSON-serializable formats."""
        if isinstance(obj, dict):
            return {k: HistoryService._sanitize_obj(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [HistoryService._sanitize_obj(v) for v in obj]
        elif hasattr(obj, "model_dump"):
            return obj.model_dump(mode="json")
        elif hasattr(obj, "dict"):
            return obj.dict()
        elif hasattr(obj, "isoformat"):  # datetime, date
            return obj.isoformat()
        elif isinstance(obj, str | int | float | bool | type(None)):
            return obj
        else:
            return str(obj)

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
