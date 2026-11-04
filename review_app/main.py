"""The review web app: upload a PDF, list documents waiting for a person, approve or reject.

Plain server-rendered HTML (Jinja2 templates), no frontend framework. The only JavaScript is the
small upload script in templates/index.html.
"""

import re
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from backend import ReviewError

BASE = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE / "templates"))

SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
DOC_ID = re.compile(r"^[0-9a-f-]{36}$")
IN_PROGRESS = {"processing"}
# Messages the page can show after a failed decision (looked up by key, never echoed from the URL).
MESSAGES = {
    "not_waiting": "That document is not waiting for review any more (already decided, or the wait ended).",
}


def safe_filename(name: str) -> str | None:
    """The file name used in the S3 key: no slashes or odd characters, PDF only."""
    name = SAFE_NAME.sub("_", Path(name.replace("\\", "/")).name).strip("._")[:100]
    return name if name.lower().endswith(".pdf") and len(name) > 4 else None


def create_app(backend=None) -> FastAPI:
    app = FastAPI(title="LexIntake review", docs_url=None, redoc_url=None, openapi_url=None)
    if backend is None:
        from backend import AwsBackend

        backend = AwsBackend()

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        return templates.TemplateResponse(
            request,
            "index.html",
            {"pending": backend.pending_reviews(), "max_mb": backend.max_upload_bytes // 1048576},
        )

    @app.post("/api/presign")
    async def presign(request: Request):
        body = await request.json()
        filename = safe_filename(str(body.get("filename", "")))
        if filename is None:
            return JSONResponse({"error": "Only .pdf files are accepted."}, status_code=400)
        size = body.get("size")
        if not isinstance(size, int) or size < 1 or size > backend.max_upload_bytes:
            mb = backend.max_upload_bytes // 1048576
            return JSONResponse({"error": f"The file must be between 1 byte and {mb} MB."}, 400)
        if not backend.reserve_upload():
            return JSONResponse(
                {"error": "The daily document limit has been reached. Try again tomorrow."}, 429
            )
        doc_id = str(uuid.uuid4())
        post = backend.presign_upload(doc_id, filename)
        return {"doc_id": doc_id, "url": post["url"], "fields": post["fields"]}

    @app.get("/doc/{doc_id}", response_class=HTMLResponse)
    def document(request: Request, doc_id: str, error: str = ""):
        error = MESSAGES.get(error, "")
        doc = backend.get_document(doc_id) if DOC_ID.match(doc_id) else None
        if doc is None:
            # Right after an upload the workflow hasn't created the record yet.
            return templates.TemplateResponse(
                request, "doc.html", {"doc": None, "doc_id": doc_id, "error": error}, status_code=404
            )
        score = backend.get_score(doc["score_key"]) if doc.get("score_key") else None
        pdf_url = backend.pdf_url(doc["s3_key"]) if doc.get("s3_key") else None
        context = {
            "doc": doc,
            "doc_id": doc_id,
            "score": score,
            "pdf_url": pdf_url,
            "refresh": doc.get("status") in IN_PROGRESS,
            "error": error,
        }
        return templates.TemplateResponse(request, "doc.html", context)

    @app.post("/doc/{doc_id}/{decision}")
    def decide(doc_id: str, decision: str):
        if decision not in ("approve", "reject") or not DOC_ID.match(doc_id):
            return JSONResponse({"error": "not found"}, status_code=404)
        try:
            (backend.approve if decision == "approve" else backend.reject)(doc_id)
        except ReviewError:
            return RedirectResponse(f"/doc/{doc_id}?error=not_waiting", status_code=303)
        return RedirectResponse(f"/doc/{doc_id}", status_code=303)

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    return app


def app_factory() -> FastAPI:
    """uvicorn --factory main:app_factory"""
    return create_app()
