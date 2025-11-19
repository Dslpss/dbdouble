import os
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URI = os.getenv("MONGO_URI") or os.getenv("PLAYNABETS_WS_URL") or ""
if not MONGO_URI:
    # Keep default empty and rely on env var in production
    MONGO_URI = None

client = None
db = None

def init_db(app=None, uri=None):
    global client, db
    uri = uri or MONGO_URI or os.getenv("MONGO_URI")
    if not uri:
        raise RuntimeError("Missing MONGO_URI environment variable")
    client = AsyncIOMotorClient(uri)
    # If Mongo returns a default DB from URI, use it; otherwise fallback to 'dbdouble'
    try:
        dbname = client.get_default_database().name
    except Exception:
        dbname = "dbdouble"
    db = client[dbname]
    # Optional: create index on users email
    async def ensure_indexes():
        await db.users.create_index("email", unique=True)
    # If an app is provided we can schedule background task
    if app:
        @app.on_event("startup")
        async def _init_indexes():
            try:
                await ensure_indexes()
            except Exception:
                pass
    else:
        # create indexes immediately (async I/O contexts should call directly)
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(ensure_indexes())
        except Exception:
            pass
