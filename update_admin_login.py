
import asyncio
import db
from datetime import datetime
from dotenv import load_dotenv
import os

load_dotenv()

async def update_admin():
    # Initialize DB
    uri = os.getenv("MONGO_URI")
    if not uri:
        print("MONGO_URI not found in env")
        return
    
    db.init_db(uri=uri)
    
    email = "dennisemannuel93@gmail.com"
    res = await db.db.users.update_one(
        {"email": email},
        {"$set": {"last_login": datetime.utcnow()}}
    )
    print(f"Updated {res.modified_count} user(s).")

if __name__ == "__main__":
    asyncio.run(update_admin())
