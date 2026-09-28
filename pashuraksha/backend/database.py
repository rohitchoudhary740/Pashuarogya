"""Database bootstrap. SQLite by default (zero-setup demo); set PASHU_DB_URL to a
PostgreSQL DSN to run on Postgres/PostGIS without code changes."""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# PASHU_DB_URL wins; DATABASE_URL is what Render/Heroku/Neon inject by default.
DB_URL = (os.environ.get("PASHU_DB_URL")
          or os.environ.get("DATABASE_URL")
          or f"sqlite:///{os.path.join(BASE_DIR, 'pashuraksha.db')}")
# SQLAlchemy 2 needs the postgresql:// scheme; managed hosts still hand out postgres://
if DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

_is_sqlite = DB_URL.startswith("sqlite")
# A wrong or unreachable Postgres host must fail fast, not hang: without a
# connect_timeout the driver waits on TCP for minutes, which on a platform
# looks like "the service never starts" rather than "the database is wrong".
_connect_args = ({"check_same_thread": False} if _is_sqlite
                 else {"connect_timeout": 10})
engine = create_engine(
    DB_URL,
    connect_args=_connect_args,
    # managed Postgres drops idle connections; recycle before it bites
    **({} if _is_sqlite else {"pool_pre_ping": True, "pool_recycle": 280}),
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
