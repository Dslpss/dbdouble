
import asyncio
import db
from datetime import datetime
from dotenv import load_dotenv
import os

load_dotenv()

async def backfill_users():
    # Initialize DB
    uri = os.getenv("MONGO_URI")
    if not uri:
        print("MONGO_URI not found in env")
        return
    
    db.init_db(uri=uri)
    
    users = await db.db.users.find({}).to_list(length=None)
    count = 0
    for u in users:
        if not u.get("last_login"):
            # Use created_at if available, else now
            fallback_date = u.get("created_at") or datetime.utcnow()
            
            await db.db.users.update_one(
                {"_id": u["_id"]},
                {"$set": {"last_login": fallback_date}}
            )
            count += 1
            print(f"Updated user {u.get('email')} with date {fallback_date}")
            
    print(f"Backfill complete. Updated {count} users.")

if __name__ == "__main__":
    asyncio.run(backfill_users())
