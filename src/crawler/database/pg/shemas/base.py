from datetime import datetime
from typing import Any, ClassVar, Self

from sqlalchemy import BigInteger, Sequence, func, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, registry
from sqlalchemy.sql.roles import ExpressionElementRole

from common.utils.aware_datetime import aware_now


class Base(DeclarativeBase):
    type_annotation_map: ClassVar = {dict[str, Any]: JSONB}

    @classmethod
    async def _create(
        cls, session: AsyncSession, **kwargs: dict[str, Any]
    ) -> Self:
        obj = cls(**kwargs)
        session.add(obj)
        return obj

    @classmethod
    async def _update(
        cls,
        session: AsyncSession,
        condition: ExpressionElementRole[Any],
        **kwargs: dict[str, Any],
    ) -> Self | None:
        return (
            await session.execute(
                update(cls).where(condition).values(**kwargs).returning(cls)
            )
        ).scalar_one_or_none()

    @classmethod
    async def get(cls, session: AsyncSession, id: int) -> Self | None:
        result = await session.get(cls, id)
        return result


class BaseSchema(Base):
    __tablename__ = "base"
    __abstract__ = True

    id = mapped_column(
        BigInteger, Sequence(f"{__tablename__}_id_seq"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(insert_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        onupdate=aware_now,
    )


metadata = Base.metadata

mapper_registry = registry(metadata=metadata)
