import asyncio
from contextlib import asynccontextmanager
import json
import time
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .auth import COOKIE, bearer, has_bearer, has_cookie, protected, same, session_value
from .config import MAX_FILE_BYTES, MAX_QUERIES, Settings
from .db import Database
from .engine import ImageEngine
from .imaging import content_hash, crop_image, decode_image
from .imports import ImportManager
from .library import Library
from .mcp import CATALOG, TOOL_NAMES, McpServer
from .sources import Uploads
from .tokens import TokenStore


class StyleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class InfoEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=60)
    value: str = Field(max_length=500)


class StyleInfo(BaseModel):
    """Optional parameters, visual traits and notes; every part may stay empty."""
    model_config = ConfigDict(extra="forbid")
    params: list[InfoEntry] = Field(default_factory=list, max_length=100)
    visual: list[InfoEntry] = Field(default_factory=list, max_length=100)
    notes: str = Field(default="", max_length=5000)


class StyleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=120)
    coverId: str | None = None
    displayOrder: list[str] | None = None
    info: StyleInfo | None = None


class Login(BaseModel):
    token: str = Field(max_length=500)


class TokenCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=60)
    tools: list[str] = Field(max_length=50)
    secret: str | None = Field(default=None, max_length=200)


class TokenUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=60)
    tools: list[str] | None = Field(default=None, max_length=50)
    secret: str | None = Field(default=None, max_length=200)
    enabled: bool | None = None


class ImportManifest(BaseModel):
    paths: list[str] = Field(default_factory=list, max_length=20000)
    # Text of each 款式信息.json, keyed by its relative path.
    infos: dict[str, str] = Field(default_factory=dict)


def read_upload(file):
    data = file.file.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("每张图片不能超过 20 MB")
    return data


def create_app(settings=None, encoder=None, start_worker=True):
    settings = settings or Settings.from_env()
    database = Database(settings.data_dir)
    engine = ImageEngine(settings, database, encoder)
    library = Library(settings, database, engine)
    imports = ImportManager(library)
    uploads = Uploads()
    tokens = TokenStore(database, TOOL_NAMES, settings.token)

    @asynccontextmanager
    async def lifespan(app):
        library.cleanup_orphans()
        if start_worker:
            engine.start()
        else:
            engine.initialize()
        yield
        engine.close()

    app = FastAPI(title="CompFinder 图片检索", version="0.1.0", lifespan=lifespan)
    app.state.library, app.state.engine, app.state.database, app.state.uploads = library, engine, database, uploads

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(LookupError)
    async def missing(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.middleware("http")
    async def require_token(request, call_next):
        path = request.url.path
        if settings.token and protected(path):
            login = has_bearer(request, settings.token) or has_cookie(request, settings.token)
            # /mcp only takes MCP tokens from the database; they may also stage uploads but reach nothing else.
            if path == "/mcp" or (path == "/api/uploads" and not login):
                granted = await run_in_threadpool(tokens.resolve, bearer(request))
                if granted is None:
                    return JSONResponse({"detail": "需要有效的 MCP 令牌"}, status_code=401, headers={"WWW-Authenticate": "Bearer"})
                request.state.mcp_tools = granted
            elif not login:
                return JSONResponse({"detail": "需要访问令牌"}, status_code=401, headers={"WWW-Authenticate": "Bearer"})
        return await call_next(request)

    @app.get("/api/auth/status")
    def auth_status(request: Request):
        token = settings.token
        return {"required": bool(token), "authenticated": not token or has_bearer(request, token) or has_cookie(request, token)}

    @app.post("/api/auth/login")
    async def login(body: Login, request: Request):
        if settings.token and not same(body.token.strip(), settings.token):
            await asyncio.sleep(1)
            raise HTTPException(401, "访问令牌不正确")
        response = JSONResponse({"ok": True})
        if settings.token:
            response.set_cookie(COOKIE, session_value(settings.token), max_age=30 * 86400, httponly=True,
                                samesite="strict", secure=request.url.scheme == "https")
        return response

    @app.post("/api/auth/logout")
    def logout():
        response = JSONResponse({"ok": True})
        response.delete_cookie(COOKIE)
        return response

    @app.get("/api/health")
    def health():
        return {"status": "ok", "app": "CompFinder"}

    @app.get("/api/admin/index")
    def index_status():
        with database.connect() as db:
            counts = {r["state"]: r["n"] for r in db.execute("SELECT state,count(*) AS n FROM images WHERE role='recognition' GROUP BY state")}
            styles = db.execute("SELECT count(*) FROM styles").fetchone()[0]
            display = db.execute("SELECT count(*) FROM images WHERE role='display'").fetchone()[0]
            searchable = db.execute("SELECT count(*) FROM styles s WHERE EXISTS (SELECT 1 FROM images d WHERE d.style_id=s.id "
                                    "AND d.role='display') AND EXISTS (SELECT 1 FROM images r WHERE r.style_id=s.id "
                                    "AND r.role='recognition' AND r.state='ready' AND r.vector_version=?)", (engine.version,)).fetchone()[0]
        return {"modelReady": engine.encoder is not None, "problem": engine.problem, "styles": styles,
                "searchableStyles": searchable, "displayImages": display, "recognitionImages": sum(counts.values()),
                "indexed": counts.get("ready", 0), "pending": counts.get("pending", 0) + counts.get("processing", 0),
                "failed": counts.get("failed", 0), "maxQueryImages": MAX_QUERIES}

    @app.post("/api/admin/index/retry")
    def retry_index():
        try:
            engine.retry()
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
        return index_status()

    @app.get("/api/styles")
    def styles(q: str = ""):
        return {"items": library.list(query=q)}

    @app.get("/api/styles/{style_id}")
    def style(style_id: str):
        result = library.get(style_id)
        if result is None:
            raise HTTPException(404, "款式不存在或尚未准备好")
        return result

    @app.get("/api/admin/styles")
    def admin_styles(q: str = ""):
        return {"items": library.list(True, q)}

    @app.post("/api/admin/styles", status_code=201)
    def create_style(body: StyleCreate):
        return library.get(library.create(body.name), True)

    @app.get("/api/admin/styles/{style_id}")
    def admin_style(style_id: str):
        result = library.get(style_id, True)
        if result is None:
            raise HTTPException(404, "款式不存在")
        return result

    @app.patch("/api/admin/styles/{style_id}")
    def update_style(style_id: str, body: StyleUpdate):
        changes = body.model_dump(exclude_unset=True)
        if any(v is None for v in changes.values()):
            raise ValueError("更新字段不能为 null")
        return library.update(style_id, changes)

    @app.delete("/api/admin/styles/{style_id}")
    def delete_style(style_id: str):
        library.delete_style(style_id)
        return {"ok": True}

    @app.post("/api/admin/styles/{style_id}/images", status_code=201)
    def add_image(style_id: str, role: str = Form(...), file: UploadFile = File(...)):
        return library.add_image(style_id, role, file.filename or "图片", read_upload(file))

    @app.delete("/api/admin/images/{image_id}")
    def delete_image(image_id: str):
        library.delete_image(image_id)
        return {"ok": True}

    def serve_image(image_id, thumbnail, admin):
        with database.connect() as db:
            row = db.execute("SELECT * FROM images WHERE id=?", (image_id,)).fetchone()
        if row is None or (not admin and row["role"] != "display"):
            raise HTTPException(404, "图片不存在")
        path = library.image_dir / (f"{image_id}.thumb.webp" if thumbnail else row["storage_name"])
        if not path.is_file():
            raise HTTPException(404, "图片文件不存在，请重新上传")
        # Image IDs are never reused and stored files are never rewritten, so browsers may cache them indefinitely.
        return FileResponse(path, media_type="image/webp" if thumbnail else "image/png",
                            headers={"Cache-Control": "private, max-age=31536000, immutable"})

    @app.get("/api/images/{image_id}")
    def image(image_id: str, thumbnail: bool = False):
        return serve_image(image_id, thumbnail, False)

    @app.get("/api/admin/images/{image_id}")
    def admin_image(image_id: str, thumbnail: bool = False):
        return serve_image(image_id, thumbnail, True)

    def search_images(images, limit, started=None):
        """Rank styles for decoded, cropped query images; identical queries count once."""
        started = started or time.perf_counter()
        # queryIndex maps each input image to its deduplicated query, so per-query scores can be shown per photo.
        queries, query_index, seen = [], [], {}
        for image in images:
            key = content_hash(image)
            if key not in seen:
                seen[key] = len(queries)
                queries.append(image)
            query_index.append(seen[key])
        result = {"queryCount": len(queries), "queryIndex": query_index}
        status = index_status()
        if not status["searchableStyles"]:
            return {**result, "items": [], "elapsedMs": 0, "message": "暂无可检索款式，请先添加展示图和识别图，并等待索引完成"}
        ranking = engine.rank(queries)
        items = []
        # Re-read current library state to exclude items deleted while inference was running.
        with database.connect() as db:
            for style_id, score, scores in ranking:
                row = db.execute("SELECT * FROM styles WHERE id=?", (style_id,)).fetchone()
                item = library.serialize(db, row) if row else None
                if item:
                    items.append({**item, "similarity": round(score, 6), "scores": [round(s, 6) for s in scores]})
                if len(items) >= limit:
                    break
        return {**result, "items": items, "elapsedMs": round((time.perf_counter() - started) * 1000),
                "message": "相似度用于外观排序，不代表型号确认概率"}

    @app.post("/api/search")
    def search(files: list[UploadFile] = File(...), crops: str = Form(""), limit: int = Query(12, ge=1, le=100)):
        if not 1 <= len(files) <= MAX_QUERIES:
            raise ValueError("一次请上传 1～6 张同一物体的照片")
        try:
            boxes = json.loads(crops) if crops else [None] * len(files)
        except (ValueError, TypeError) as exc:
            raise ValueError("框选数据不是有效的 JSON") from exc
        if not isinstance(boxes, list) or len(boxes) != len(files):
            raise ValueError("框选数量必须与查询图片数量一致")
        started = time.perf_counter()
        images = [crop_image(decode_image(read_upload(file)), box) for file, box in zip(files, boxes)]
        try:
            return search_images(images, limit, started)
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.post("/api/uploads", status_code=201)
    def upload(file: UploadFile = File(...)):
        """Lets AI clients hand over local files, then reference them in MCP tools as upload:<id>."""
        return {"id": uploads.add(read_upload(file)), "expiresInSeconds": uploads.ttl}

    mcp = McpServer(library, search_images, index_status, uploads)

    @app.post("/mcp")
    async def mcp_endpoint(request: Request):
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "不允许跨站访问"}, status_code=403)
        try:
            message = json.loads(await request.body())
        except ValueError:
            return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}, status_code=400)
        # Without authentication (tests only) no grant is recorded and every tool is available.
        answer = await run_in_threadpool(mcp.handle, message, getattr(request.state, "mcp_tools", None))
        return Response(status_code=202) if answer is None else JSONResponse(answer)

    @app.get("/api/admin/tokens")
    def list_tokens():
        return {"items": tokens.list(), "tools": CATALOG}

    @app.post("/api/admin/tokens", status_code=201)
    def create_token(body: TokenCreate):
        return tokens.create(body.name, body.tools, body.secret)

    @app.patch("/api/admin/tokens/{token_id}")
    def update_token(token_id: str, body: TokenUpdate):
        changes = body.model_dump(exclude_unset=True)
        if any(value is None for value in changes.values()):
            raise ValueError("更新字段不能为 null")
        return tokens.update(token_id, changes)

    @app.delete("/api/admin/tokens/{token_id}")
    def delete_token(token_id: str):
        tokens.delete(token_id)
        return {"ok": True}

    @app.api_route("/mcp", methods=["GET", "DELETE"])
    def mcp_stream():
        # Stateless JSON-only server: no server-initiated stream and no sessions to end.
        return Response(status_code=405, headers={"Allow": "POST"})

    @app.post("/api/admin/imports/preview")
    def preview_import(body: ImportManifest):
        return imports.preview(body.paths, body.infos)

    @app.post("/api/admin/imports", status_code=201)
    def create_import(body: ImportManifest):
        return imports.create(body.paths, body.infos)

    @app.get("/api/admin/imports")
    def list_imports():
        with database.connect() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM imports ORDER BY created_at DESC LIMIT 10")]
        return {"items": [{k: v for k, v in imports.get(job_id).items() if k != "files"} for job_id in ids]}

    @app.get("/api/admin/imports/{job_id}")
    def get_import(job_id: str):
        return imports.get(job_id)

    @app.post("/api/admin/imports/{job_id}/files")
    def import_file(job_id: str, path: str = Form(...), file: UploadFile = File(...)):
        return imports.upload(job_id, path, read_upload(file))

    @app.post("/api/admin/imports/{job_id}/finish")
    def finish_import(job_id: str):
        return imports.finish(job_id)

    # Unmatched API paths must never fall through to the SPA.
    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def missing_api(path: str):
        raise HTTPException(404, "接口不存在")

    if (settings.frontend_dir / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=settings.frontend_dir / "assets"), name="frontend-assets")

    @app.get("/{path:path}")
    def frontend(path: str):
        index = settings.frontend_dir / "index.html"
        if index.is_file():
            return FileResponse(index)
        return JSONResponse({"message": "前端尚未构建，请运行 scripts/setup.ps1；开发模式访问 Vite 服务", "docs": "/docs"})

    return app


app = create_app()
