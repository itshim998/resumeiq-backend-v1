from flask_cors import CORS
from flask import Flask, request, jsonify, Response
from werkzeug.utils import secure_filename
from flask import send_file
from io import BytesIO
import logging
import os
from bson import ObjectId

from profile_parser import parse_profile_input
from profile_structurer import structure_and_store_profile
from profile_repository import (
    get_profile_by_id,
    list_profiles
)
from resume_generator import generate_resume_from_profile
from resume_repository import get_resume_by_id
from ats_analyzer import analyze_resume
from resume_renderer import render_resume_pdf

# Portfolio imports
from portfolio_generator import generate_portfolio
from portfolio_repository import get_portfolio_by_id

app = Flask(__name__)

# ✅ CORS Configuration - Allow React frontend
# CORS origins may be set via the environment variable `CORS_ORIGINS`
# as a comma-separated list. Defaults to the production frontends.
cors_origins = os.environ.get(
    "CORS_ORIGINS",
    "https://recruiteriq.sentiqlabs.com,https://resumeiq.sentiqlabs.com,https://resumeiqv1.sentiqlabs.com,http://localhost:5173,http://localhost:3000"
).split(",")

CORS(app, resources={
    r"/api/*": {
        "origins": cors_origins,
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type"]
    }
})


# ✅ Configure logging for debugging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ✅ Helper: Serialize MongoDB documents to JSON-safe format
def _serialize_doc(doc):
    """
    Convert MongoDB document to JSON-serializable format.
    Handles ObjectId and datetime conversions.
    """
    if not doc:
        return doc
    
    if isinstance(doc, dict):
        doc = dict(doc)
        if "_id" in doc and isinstance(doc["_id"], ObjectId):
            doc["_id"] = str(doc["_id"])
        
        # Convert datetime objects
        for key in ["created_at", "updated_at"]:
            if key in doc and hasattr(doc[key], "isoformat"):
                doc[key] = doc[key].isoformat()
        
        return doc
    
    return doc

# ------------------------------
# Root & Documentation
# ------------------------------
@app.route("/")
def root():
    """Welcome and API documentation"""
    return jsonify({
        "service": "ResumeIQ API",
        "version": "1.0",
        "status": "running",
        "endpoints": {
            "health": "/ping",
            "profiles": {
                "ingest": "POST /api/profile/ingest",
                "list": "GET /api/profiles",
                "get": "GET /api/profile/<profile_id>"
            },
            "resumes": {
                "generate": "POST /api/resume/generate",
                "get": "GET /api/resume/<resume_id>",
                "render": "GET /api/resume/render/<resume_id>"
            },
            "ats": {
                "analyze": "POST /api/ats/analyze/<resume_id>"
            },
            "portfolio": {
                "generate": "POST /api/portfolio/generate",
                "download": "GET /api/portfolio/download/<portfolio_id>"
            }
        },
        "debug": "//__routes"
    }), 200

# ------------------------------
# Health
# ------------------------------
@app.route("/ping")
def ping():
    return ("ok", 200)

# ------------------------------
# Resume PDF Rendering (Download)
# ------------------------------
@app.route("/api/resume/render/<resume_id>", methods=["GET"])
def render_resume(resume_id):
    try:
        pdf_bytes, filename = render_resume_pdf(resume_id)

        return send_file(
            BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name="resume.pdf"
        )

    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Profile
# ------------------------------

@app.route("/api/profile/ingest", methods=["GET", "POST", "OPTIONS"])
def ingest_profile_post():
    """
    Ingest profile from three sources:
    1. JSON body (React): { "text": "..." }
    2. Form data (HTML forms): text=...
    3. File upload (multipart): file=...
    """
    
    try:
        # ✅ Log incoming request
        logger.info(f"[INGEST] Method: {request.method}")
        logger.info(f"[INGEST] Headers: {dict(request.headers)}")
        logger.info(f"[INGEST] Content-Type: {request.content_type}")
        
        # ✅ Handle preflight
        if request.method == "OPTIONS":
            return jsonify({"ok": True}), 200
        
        # 1️⃣ Try JSON first (React / API clients)
        json_data = request.get_json(silent=True)
        if json_data:
            logger.info(f"[INGEST] Received JSON data")
            profile_text = json_data.get("text", "").strip()

            # If frontend posted name/contact separately, prepend them to the text
            # so the structuring LLM can extract contact fields (email, phone, links)
            name_field = (json_data.get("name") or "").strip()
            contact_field = (json_data.get("contact") or "").strip()
            prefix_parts = []
            if name_field:
                prefix_parts.append(f"Name: {name_field}")
            if contact_field:
                prefix_parts.append(f"Contact: {contact_field}")

            if prefix_parts:
                profile_text = "\n".join(prefix_parts) + "\n\n" + profile_text
            
            if not profile_text:
                logger.warning("[INGEST] JSON received but 'text' field is empty")
                return jsonify({"error": "Field 'text' is required and must not be empty"}), 400
            
            logger.info(f"[INGEST] Text length: {len(profile_text)} characters")
        else:
            # 2️⃣ Try form text (HTML forms / legacy)
            profile_text = request.form.get("text", "").strip()
            if profile_text:
                logger.info(f"[INGEST] Received form data, text length: {len(profile_text)}")
            else:
                # 3️⃣ Try file upload
                file = request.files.get("file")
                if file:
                    logger.info(f"[INGEST] Received file upload: {file.filename}")
                    try:
                        profile_text = parse_profile_input(
                            file_bytes=file.read(),
                            filename=secure_filename(file.filename)
                        )
                        logger.info(f"[INGEST] File parsed, text length: {len(profile_text)}")
                    except Exception as e:
                        logger.error(f"[INGEST] File parsing failed: {e}")
                        return jsonify({"error": f"File parsing failed: {str(e)}"}), 400
                else:
                    logger.error("[INGEST] No input provided (no JSON, form, or file)")
                    return jsonify({"error": "No input provided. Send 'text' field in JSON or form, or upload a file"}), 400
        
        # ✅ Parse and structure profile
        logger.info(f"[INGEST] Parsing profile text...")
        try:
            parsed_text = parse_profile_input(manual_text=profile_text)
            logger.info(f"[INGEST] Profile parsed successfully")
        except Exception as e:
            logger.error(f"[INGEST] Profile parsing error: {e}")
            return jsonify({"error": f"Profile parsing failed: {str(e)}"}), 400
        
        # ✅ Structure and store
        logger.info(f"[INGEST] Structuring and storing profile...")
        try:
            profile = structure_and_store_profile(parsed_text, source="manual")
            logger.info(f"[INGEST] Profile stored successfully with ID: {profile.get('_id')}")
        except Exception as e:
            logger.error(f"[INGEST] Structuring/storage error: {e}")
            return jsonify({"error": f"Profile structuring failed: {str(e)}"}), 400
        
        # ✅ Ensure JSON serializable
        profile = _serialize_doc(profile)
        logger.info(f"[INGEST] Response: {profile.get('_id')}")
        return jsonify(profile), 201
    
    except Exception as e:
        logger.exception(f"[INGEST] Unexpected error: {e}")
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500


@app.route("/api/resume/generate", methods=["POST"])
def generate_resume():
    try:
        data = request.json or {}
        profile_id = data.get("profile_id")
        job_description = data.get("job_description")
        
        if not profile_id:
            return jsonify({"error": "profile_id is required"}), 400
        
        resume = generate_resume_from_profile(
            profile_id=profile_id,
            job_description=job_description
        )
        
        # ✅ Ensure JSON serializable
        resume = _serialize_doc(resume)
        return jsonify(resume), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.exception(f"[RESUME_GENERATE] Error: {e}")
        return jsonify({"error": str(e)}), 500




@app.route("/api/profile/<profile_id>")
def get_profile(profile_id):
    try:
        profile = get_profile_by_id(profile_id)
        if not profile:
            return jsonify({"error": "Profile not found"}), 404
        # ✅ Ensure JSON serializable
        profile = _serialize_doc(profile)
        return jsonify(profile), 200
    except Exception as e:
        logger.error(f"[GET_PROFILE] Error: {e}")
        return jsonify({"error": str(e)}), 400


@app.route("/api/profiles")
def profiles():
    try:
        profile_list = list_profiles()
        # ✅ Ensure all profiles are JSON serializable
        profile_list = [_serialize_doc(p) for p in profile_list]
        return jsonify(profile_list), 200
    except Exception as e:
        logger.error(f"[LIST_PROFILES] Error: {e}")
        return jsonify({"error": str(e)}), 500



@app.route("/api/resume/<resume_id>")
def get_resume(resume_id):
    try:
        resume = get_resume_by_id(resume_id)
        if not resume:
            return jsonify({"error": "Resume not found"}), 404
        # ✅ Ensure JSON serializable
        resume = _serialize_doc(resume)
        return jsonify(resume), 200
    except Exception as e:
        logger.error(f"[GET_RESUME] Error: {e}")
        return jsonify({"error": str(e)}), 500


# ------------------------------
# ATS
# ------------------------------
@app.route("/api/ats/analyze/<resume_id>", methods=["POST"])
def ats_analyze(resume_id):
    try:
        data = request.json or {}
        job_description = data.get("job_description", "")
        
        if not job_description:
            return jsonify({"error": "job_description is required"}), 400
        
        report = analyze_resume(resume_id, job_description)
        # ✅ Ensure JSON serializable
        report = _serialize_doc(report)
        return jsonify(report), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.exception(f"[ATS_ANALYZE] Error: {e}")
        return jsonify({"error": str(e)}), 500


# ------------------------------
# Rendering
#-----------------------------


# ------------------------------
# Portfolio Generation (STRICTLY resume-dependent)
# ------------------------------
@app.route("/api/portfolio/generate", methods=["POST"])
def portfolio_generate():
    """
    Generate a portfolio from a resume.
    
    CRITICAL: resume_id is MANDATORY
    """
    try:
        data = request.json or {}
        resume_id = data.get("resume_id")
        profile_id = data.get("profile_id")
        
        # ENFORCE: resume_id is required
        if not resume_id:
            return jsonify({
                "error": "resume_id is required. Portfolio cannot be generated without a resume."
            }), 400
        
        if not profile_id:
            return jsonify({"error": "profile_id is required"}), 400
        
        portfolio = generate_portfolio(resume_id, profile_id)
        # ✅ Ensure JSON serializable
        portfolio = _serialize_doc(portfolio)
        return jsonify({
            "portfolio_id": portfolio["_id"],
            "created_at": portfolio.get("created_at")
        }), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception(f"[PORTFOLIO_GENERATE] Error: {e}")
        return jsonify({
            "error": "Failed to generate portfolio",
            "detail": str(e)
        }), 500


@app.route("/api/portfolio/download/<portfolio_id>", methods=["GET"])
def portfolio_download(portfolio_id):
    """
    Download portfolio as static HTML file.
    
    Returns:
        Raw HTML with proper download headers
    """
    try:
        portfolio = get_portfolio_by_id(portfolio_id)
        
        if not portfolio:
            return jsonify({"error": "Portfolio not found"}), 404
        
        html = portfolio.get("html", "")
        
        # FAIL LOUDLY if HTML is too short
        if len(html) < 500:
            return jsonify({
                "error": "Portfolio HTML is corrupted or incomplete"
            }), 500
        
        response = Response(html, mimetype="text/html")
        response.headers["Content-Disposition"] = (
            f"attachment; filename=portfolio_{portfolio['profile_id']}.html"
        )
        
        return response
    except Exception as e:
        logger.exception(f"[PORTFOLIO_DOWNLOAD] Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/__routes")
def show_routes():
    return str(app.url_map)




# ------------------------------
# Entry
# ------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)



