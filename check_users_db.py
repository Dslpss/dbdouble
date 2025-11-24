
import asyncio
import db
from datetime import datetime
from dotenv import load_dotenv
import os

load_dotenv()

async def check():
    # Initialize DB
    uri = os.getenv("MONGO_URI")
    if not uri:
        print("MONGO_URI not found in env")
        return
    
    db.init_db(uri=uri)
    
    users = await db.db.users.find({}).to_list(length=None)
    for u in users:
        print(f"User: {u.get('email')}")
        print(f"  last_login: {u.get('last_login')} (Type: {type(u.get('last_login'))})")

if __name__ == "__main__":
    asyncio.run(check())
