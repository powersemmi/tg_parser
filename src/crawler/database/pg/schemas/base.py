from datetime import datetime
from typing import Any, ClassVar, Self

from pydantic.alias_generators import to_snake
from sqlalchemy import TIMESTAMP, BigInteger, Sequence, func, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    declared_attr,
    mapped_column,
    registry,
)
from sqlalchemy.sql.roles import ExpressionElementRole

from common.utils.aware_datetime import aware_now


class Base(DeclarativeBase):
    type_annotation_map: ClassVar = {dict[str, Any]: JSONB}

    @classmethod
    async def _create(cls, session: AsyncSession, **kwargs: Any) -> Self:
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
    __abstract__ = True

    @declared_attr.directive
    def __tablename__(cls) -> str:  # noqa: N805
        # Автоматически генерируем имена таблиц из имени класса
        return to_snake(cls.__name__)

    @declared_attr
    def id(cls) -> Mapped[int]:  # noqa: N805
        return mapped_column(
            BigInteger,
            Sequence(f"{cls.__tablename__}_id_seq"),
            primary_key=True,
        )

    @declared_attr
    def created_at(cls) -> Mapped[datetime]:  # noqa: N805
        return mapped_column(
            TIMESTAMP(timezone=True), insert_default=func.now()
        )

    @declared_attr
    def updated_at(cls) -> Mapped[datetime]:  # noqa: N805
        return mapped_column(
            TIMESTAMP(timezone=True),
            server_default=func.now(),
            onupdate=aware_now,
        )


metadata = Base.metadata

mapper_registry = registry(metadata=metadata)
