import os
from pymongo import MongoClient

# Read MongoDB URI from environment (exact variable required by Render)
MONGO_URI = os.environ.get("MONGO_URI")
if not MONGO_URI:
    raise RuntimeError("MONGO_URI environment variable is required for MongoDB connection")

# Initialize a single global client and expose `db` for use across the app
client = MongoClient(MONGO_URI)

# Default database name (can be overridden in environment)
DB_NAME = os.environ.get("RESUMEIQ_DB", "sentiq_resumeiq")
db = client[DB_NAME]
