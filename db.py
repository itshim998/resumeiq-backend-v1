import os
from pymongo import MongoClient
from datetime import datetime
from typing import List, Dict, Optional

# Read MongoDB URI from environment (exact variable required by Render)
MONGO_URI = os.environ.get("MONGO_URI")
if not MONGO_URI:
    raise RuntimeError("MONGO_URI environment variable is required for MongoDB connection")

# Initialize a single global client and expose `db` for use across the app
client = MongoClient(MONGO_URI)

# Default database name (can be overridden in environment)
DB_NAME = os.environ.get("RESUMEIQ_DB", "sentiq_resumeiq")
db = client[DB_NAME]

# Collections for web_app.py (RecruiterIQ functionality)
candidates_collection = db["candidates"]


def init_db():
    """
    Initialize database collections and indexes.
    This is called once on app startup.
    """
    try:
        # Create indexes for better query performance
        candidates_collection.create_index([("created_at", -1)])
        candidates_collection.create_index([("score", -1)])
    except Exception as e:
        print(f"Warning: Could not create indexes: {e}")


def list_candidates(limit: int = 100) -> List[Dict]:
    """
    List all candidates from the database.
    
    Args:
        limit: Maximum number of candidates to return
        
    Returns:
        List of candidate documents
    """
    try:
        candidates = list(
            candidates_collection.find()
            .sort("created_at", -1)
            .limit(limit)
        )
        
        # Serialize MongoDB documents
        for candidate in candidates:
            if "_id" in candidate:
                candidate["id"] = str(candidate["_id"])
                del candidate["_id"]
        
        return candidates
    except Exception as e:
        print(f"Error listing candidates: {e}")
        return []


def get_candidate(candidate_id: int) -> Optional[Dict]:
    """
    Get a single candidate by ID.
    
    Args:
        candidate_id: The candidate's ID
        
    Returns:
        Candidate document or None if not found
    """
    try:
        candidate = candidates_collection.find_one({"id": candidate_id})
        
        if candidate:
            candidate["id"] = str(candidate.get("_id", candidate_id))
            if "_id" in candidate:
                del candidate["_id"]
        
        return candidate
    except Exception as e:
        print(f"Error getting candidate: {e}")
        return None


def delete_all_candidates():
    """
    Delete all candidates from the database.
    Used for clearing dashboard data.
    """
    try:
        result = candidates_collection.delete_many({})
        print(f"Deleted {result.deleted_count} candidates")
    except Exception as e:
        print(f"Error deleting candidates: {e}")
        raise

