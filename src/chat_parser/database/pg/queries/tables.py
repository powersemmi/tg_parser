from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def check_exists(session: AsyncSession, schema: str, name: str) -> bool:
    sql = text(
        """
        SELECT EXISTS (
            SELECT FROM information_schema.tables
            WHERE  table_schema = :schema
            AND    table_name   = :name
        );
        """
    )
    res = (
        await session.execute(sql, {"schema": schema, "name": name})
    ).scalar()
    return bool(res)
