from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.config import DATABASE_URL
from sqlalchemy.orm import declarative_base

engine = create_async_engine(DATABASE_URL, echo=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

Base = declarative_base()
