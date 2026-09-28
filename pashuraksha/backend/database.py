"""Database bootstrap. SQLite by default (zero-setup demo); set PASHU_DB_URL or
DATABASE_URL to a PostgreSQL DSN to run on Postgres/PostGIS without code changes."""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_env():
    for p in (os.path.join(BASE_DIR, "..", "..", ".env"),
              os.path.join(BASE_DIR, "..", ".env"),
              os.path.join(BASE_DIR, ".env")):
        try:
            if os.path.exists(p):
                with open(p, encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        k, v = line.split("=", 1)
                        val = v.strip().strip('"').strip("'")
                        if val and k.strip() not in os.environ:
                            os.environ[k.strip()] = val
        except OSError:
            pass


_load_env()

# Detect Vercel environment
is_vercel = bool(os.environ.get("VERCEL"))

# DATABASE_URL is read from the environment (e.g. Neon on Vercel); PASHU_DB_URL supported as alternative.
raw_url = (os.environ.get("DATABASE_URL") or os.environ.get("PASHU_DB_URL") or "").strip()

if raw_url:
    DB_URL = raw_url
    # SQLAlchemy 2 requires postgresql:// scheme; managed providers often provide postgres://
    if DB_URL.startswith("postgres://"):
        DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)
elif is_vercel:
    # On Vercel, external Postgres (DATABASE_URL / PASHU_DB_URL) should be configured.
    # Fallback to writable /tmp so SQLite does not fail on read-only deployment filesystems.
    tmp_dir = "/tmp"
    os.makedirs(tmp_dir, exist_ok=True)
    DB_URL = f"sqlite:///{os.path.join(tmp_dir, 'pashuraksha.db')}"
else:
    # Local development: ensure local directory exists and use local SQLite database
    os.makedirs(BASE_DIR, exist_ok=True)
    DB_URL = f"sqlite:///{os.path.join(BASE_DIR, 'pashuraksha.db')}"

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
