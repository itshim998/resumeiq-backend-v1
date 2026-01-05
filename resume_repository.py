"""
resume_repository.py
--------------------
Handles MongoDB access for resumes.
"""

import os
from pymongo import MongoClient
from bson import ObjectId
from dotenv import load_dotenv

load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("RESUMEIQ_DB", "sentiq_resumeiq")

client = MongoClient(MONGODB_URI)
db = client[DB_NAME]
resumes_collection = db["resumes"]


def _serialize_resume(doc):
    """
    Convert MongoDB document to JSON-safe dict.
    """
    if not doc:
        return doc
    
    doc = dict(doc)
    if "_id" in doc:
        doc["_id"] = str(doc["_id"])
    if "profile_id" in doc and hasattr(doc["profile_id"], "__str__") and str(type(doc["profile_id"])) == "<class 'bson.objectid.ObjectId'>":
        doc["profile_id"] = str(doc["profile_id"])
    
    # Convert datetime objects to ISO format strings
    if "created_at" in doc and hasattr(doc["created_at"], "isoformat"):
        doc["created_at"] = doc["created_at"].isoformat()
    
    return doc


def get_resume_by_id(resume_id: str):
    """
    Fetch a resume document by ID.

    Args:
        resume_id (str): Resume MongoDB ObjectId as string

    Returns:
        dict | None
    """
    try:
        return _serialize_resume(resumes_collection.find_one({"_id": ObjectId(resume_id)}))
    except Exception:
        return None
