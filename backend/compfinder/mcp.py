"""MCP endpoint (streamable HTTP, stateless, JSON responses) so AI clients can search and build the library."""
import base64
from io import BytesIO
import json
import logging
from pathlib import PurePosixPath
import urllib.parse

from PIL import Image, ImageOps

from .config import MAX_QUERIES
from .imaging import crop_image, decode_image
from .imports import info_rows
from .library import clean_info
from .sources import load_image, read_page
from .taxonomy import check_visual, describe

log = logging.getLogger(__name__)
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
INSTRUCTIONS = """CompFinder 是轻触开关等元件的以图寻物图库。每个款式有展示图（给人看）和识别图（以图搜图用的参考图，最好是多角度实拍）。
- search_by_image 的相似度只用于排序，不是正确概率；请结合返回的缩略图和款式信息判断，没有把握时说明“库里可能没有”。
- 视觉信息必须使用 ytst 规范 v1.1 的字段和可选值（visual_taxonomy），只写能确认的字段。
- 图片来源：公网 http(s) 链接、data:image/...;base64,...，或先 POST /api/uploads 上传得到的 upload:<id>。
- 本接口不提供删除；删除和调整请在网页管理端操作。"""

CROP = {"type": "object", "description": "可选框选，按图片宽高的比例 0～1，至少 24×24 像素",
        "properties": {key: {"type": "number"} for key in ("x", "y", "width", "height")},
        "required": ["x", "y", "width", "height"], "additionalProperties": False}
SOURCE = {"type": "string", "description": "http(s) 图片链接、data:image/...;base64,... 或 upload:<id>"}
IMAGE_ITEM = {"type": "object", "properties": {"image": SOURCE, "crop": CROP}, "required": ["image"], "additionalProperties": False}
INFO_GROUP = {"type": "object", "description": "{名称: 内容}；内容可以是文字、数字、true/false 或列表",
              "additionalProperties": {"type": ["string", "number", "boolean", "array"], "items": {"type": ["string", "number"]}}}
INFO_PROPERTIES = {
    "visual": {**INFO_GROUP, "description": "视觉信息，字段名和取值必须符合 visual_taxonomy；看不清的字段省略"},
    "params": {**INFO_GROUP, "description": "参数，如原厂料号、制造商、额定电压等，来自页面或资料"},
    "notes": {"type": "string", "description": "备注，建议写明信息和图片的来源网址"},
}


def schema(properties=None, required=()):
    return {"type": "object", "properties": properties or {}, "required": list(required), "additionalProperties": False}


TOOLS = [
    {"name": "library_status", "title": "图库状态", "description": "图库与识别引擎状态：款式数、可检索款式数、索引进度。", "inputSchema": schema()},
    {"name": "visual_taxonomy", "title": "视觉信息规范", "description": "ytst 轻触开关规范 v1.1：视觉信息可用的字段、可选值和优先填写的关键结构。写视觉信息前先看。",
     "inputSchema": schema()},
    {"name": "read_page", "title": "读取网页", "description": "读取公开网页的标题、正文和图片地址（含页面脚本里的商品图），用于从商品页提取按钮信息和候选图片。"
     "需要登录或完全靠脚本渲染的页面可能读不到内容。", "inputSchema": schema({"url": {"type": "string"}}, ["url"])},
    {"name": "preview_image", "title": "查看图片", "description": "查看一张图片（缩小到最长边 1024）并返回原始尺寸；可带 crop 预览框选效果。加入图库前用它确认是同一款并决定框选。",
     "inputSchema": schema({"image": SOURCE, "crop": CROP}, ["image"])},
    {"name": "search_by_image", "title": "以图搜图", "description": "以图搜图：1～6 张同一物体的照片，返回最相似的款式、相似度、款式信息和前几名的封面缩略图。",
     "inputSchema": schema({"images": {"type": "array", "items": IMAGE_ITEM, "minItems": 1, "maxItems": MAX_QUERIES},
                            "limit": {"type": "integer", "minimum": 1, "maximum": 12, "default": 5}}, ["images"])},
    {"name": "list_styles", "title": "查找款式", "description": "列出图库中的款式（含草稿），可按名称、参数、视觉信息查找。",
     "inputSchema": schema({"query": {"type": "string", "description": "可选查找词，如型号"}})},
    {"name": "get_style", "title": "款式详情", "description": "查看一个款式的详情、款式信息和缩略图。",
     "inputSchema": schema({"style_id": {"type": "string"},
                            "thumbnails": {"type": "string", "enum": ["display", "recognition", "none"], "default": "display"}}, ["style_id"])},
    {"name": "create_style", "title": "新建款式", "description": "新建款式（名称不能与已有款式重复），可同时写入款式信息。之后用 add_images 加展示图和识别图。",
     "inputSchema": schema({"name": {"type": "string", "description": "款式名称，建议用型号或“品牌 型号”"}, **INFO_PROPERTIES}, ["name"])},
    {"name": "add_images", "title": "添加图片", "description": "给款式添加图片，每次 1～20 张，逐张返回结果。display 为展示图，recognition 为识别图"
     "（会在后台建立索引）。同一集合内相同图片自动去重。",
     "inputSchema": schema({"style_id": {"type": "string"}, "role": {"type": "string", "enum": ["display", "recognition"]},
                            "images": {"type": "array", "items": IMAGE_ITEM, "minItems": 1, "maxItems": 20}},
                           ["style_id", "role", "images"])},
    {"name": "update_style_info", "title": "修改款式信息", "description": "更新款式信息。只替换传入的部分（visual、params、notes），未传入的部分保持不变。",
     "inputSchema": schema({"style_id": {"type": "string"}, **INFO_PROPERTIES}, ["style_id"])},
]

# How the token page groups tools; every tool belongs to exactly one group.
TOOL_GROUPS = (("查询图库", ("search_by_image", "list_styles", "get_style", "library_status", "visual_taxonomy")),
               ("读取网页与图片", ("read_page", "preview_image")),
               ("写入图库", ("create_style", "add_images", "update_style_info")))
TOOL_NAMES = tuple(tool["name"] for tool in TOOLS)
CATALOG = [{"name": tool["name"], "title": tool["title"], "description": tool["description"],
            "group": next(group for group, names in TOOL_GROUPS if tool["name"] in names),
            "writes": tool["name"] in dict(TOOL_GROUPS)["写入图库"]} for tool in TOOLS]


def text(value):
    return {"type": "text", "text": value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)}


def picture(image, side):
    image = ImageOps.contain(image.convert("RGB"), (side, side))
    stream = BytesIO()
    image.save(stream, "JPEG", quality=82)
    return {"type": "image", "data": base64.b64encode(stream.getvalue()).decode("ascii"), "mimeType": "image/jpeg"}


def reply(message_id, result):
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def failure(message_id, code, message):
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def required(args, key, kind=str):
    value = args.get(key)
    if not isinstance(value, kind) or (kind is str and not value.strip()):
        raise ValueError(f"缺少参数 {key}")
    return value.strip() if kind is str else value


def entries(info):
    return "；".join(f"{e['name']} {e['value']}".strip() for group in ("params", "visual") for e in info.get(group, []))


class McpServer:
    def __init__(self, library, search, status, uploads):
        self.library, self.search, self.status, self.uploads = library, search, status, uploads
        self.tools = {tool["name"]: getattr(self, tool["name"]) for tool in TOOLS}

    def handle(self, message, allowed=None):
        """One JSON-RPC message or a batch; None means nothing to send back (HTTP 202).

        allowed is the set of tools the caller's token grants; None grants every tool.
        """
        if isinstance(message, list):
            replies = [r for r in (self.handle_one(m, allowed) for m in message) if r is not None]
            return replies or None
        return self.handle_one(message, allowed)

    def handle_one(self, message, allowed=None):
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return failure(None, -32600, "Invalid Request")
        if "method" not in message or "id" not in message:
            return None  # Notifications and the client's own responses need no answer.
        message_id, method, params = message["id"], message["method"], message.get("params") or {}
        if not isinstance(params, dict):
            return failure(message_id, -32602, "params 必须是对象")
        if method == "initialize":
            requested = params.get("protocolVersion")
            return reply(message_id, {"protocolVersion": requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                                      "capabilities": {"tools": {"listChanged": False}},
                                      "serverInfo": {"name": "compfinder", "title": "CompFinder 以图寻物", "version": "0.2.0"},
                                      "instructions": INSTRUCTIONS})
        if method == "ping":
            return reply(message_id, {})
        if method == "tools/list":
            return reply(message_id, {"tools": [tool for tool in TOOLS if allowed is None or tool["name"] in allowed]})
        if method != "tools/call":
            return failure(message_id, -32601, f"不支持的方法：{method}")
        name, args = params.get("name"), params.get("arguments") or {}
        if name not in self.tools or not isinstance(args, dict):
            return failure(message_id, -32602, f"未知工具或参数无效：{name}")
        if allowed is not None and name not in allowed:
            return failure(message_id, -32602, f"此令牌无权使用工具：{name}")
        try:
            return reply(message_id, {"content": self.tools[name](args), "isError": False})
        except (ValueError, LookupError, RuntimeError, OSError) as exc:
            return reply(message_id, {"content": [text(str(exc))], "isError": True})
        except Exception:
            log.exception("MCP tool %s failed", name)
            return reply(message_id, {"content": [text("服务内部错误，请查看服务日志")], "isError": True})

    def image(self, item):
        if isinstance(item, str):
            item = {"image": item}
        if not isinstance(item, dict):
            raise ValueError("图片项应为 {image, crop}")
        return crop_image(decode_image(load_image(item.get("image"), self.uploads)), item.get("crop"))

    def thumbnails(self, image_ids):
        """Image blocks for stored thumbnails; a missing file is skipped rather than failing the call."""
        blocks = []
        for image_id in image_ids:
            try:
                with Image.open(self.library.image_dir / f"{image_id}.thumb.webp") as source:
                    blocks.append(picture(source, 480))
            except OSError:
                continue
        return blocks

    def info(self, args):
        """Only the groups the caller passed, cleaned and checked against the taxonomy."""
        info = {}
        for key, label in (("visual", "视觉信息"), ("params", "参数")):
            if key in args:
                info[key] = info_rows(args[key], label)
        if "notes" in args:
            if not isinstance(args["notes"], str):
                raise ValueError("notes 应为文字")
            info["notes"] = args["notes"]
        cleaned = clean_info(info)
        check_visual(cleaned["visual"])
        return {key: cleaned[key] for key in info}

    def library_status(self, args):
        return [text(self.status())]

    def visual_taxonomy(self, args):
        return [text(describe())]

    def read_page(self, args):
        return [text(read_page(required(args, "url")))]

    def preview_image(self, args):
        original = decode_image(load_image(required(args, "image"), self.uploads))
        shown = crop_image(original, args.get("crop"))
        return [text({"width": original.width, "height": original.height, "cropped": shown.size != original.size,
                      "shownWidth": shown.width, "shownHeight": shown.height}), picture(shown, 1024)]

    def search_by_image(self, args):
        items = required(args, "images", list)
        if not 1 <= len(items) <= MAX_QUERIES:
            raise ValueError("一次请提供 1～6 张同一物体的照片")
        limit = args.get("limit", 5)
        if not isinstance(limit, int) or not 1 <= limit <= 12:
            raise ValueError("limit 应为 1～12")
        result = self.search([self.image(item) for item in items], limit)
        candidates = [{"rank": rank, "id": item["id"], "name": item["name"], "similarity": round(item["similarity"] * 100, 1),
                       "perPhoto": [round(s * 100, 1) for s in item["scores"]], "displayCount": item["displayCount"],
                       "info": item["info"]} for rank, item in enumerate(result["items"], 1)]
        content = [text({"message": result["message"], "queryCount": result["queryCount"], "queryIndex": result["queryIndex"],
                         "candidates": candidates})]
        for candidate, item in zip(candidates[:4], result["items"]):
            if item["cover"]:
                content += [text(f"第 {candidate['rank']} 名「{item['name']}」的封面"), *self.thumbnails([item["cover"]["id"]])]
        return content

    def list_styles(self, args):
        query = args.get("query") or ""
        if not isinstance(query, str):
            raise ValueError("query 应为文字")
        items = self.library.list(True, query)
        return [text({"total": len(items), "items": [
            {"id": item["id"], "name": item["name"], "state": item["state"], "displayCount": item["displayCount"],
             "recognitionCount": item["recognitionCount"], "indexedCount": item["indexedCount"], "info": entries(item["info"])}
            for item in items[:100]]})]

    def get_style(self, args):
        style = self.library.get(required(args, "style_id"), True)
        if style is None:
            raise LookupError("款式不存在")
        role = args.get("thumbnails", "display")
        if role not in {"display", "recognition", "none"}:
            raise ValueError("thumbnails 只能是 display、recognition 或 none")
        summary = {key: style[key] for key in ("id", "name", "state", "missing", "displayCount", "recognitionCount",
                                               "indexedCount", "pendingCount", "failedCount", "info")}
        summary["recognitionStates"] = [image["state"] for image in style["recognitionImages"]]
        content = [text(summary)]
        if role != "none":
            content += self.thumbnails([image["id"] for image in style["displayImages" if role == "display" else "recognitionImages"][:6]])
        return content

    def create_style(self, args):
        name, info = required(args, "name"), self.info(args)
        style_id = self.library.create(name)
        if info:
            self.library.update(style_id, {"info": info})
        return [text(self.brief(style_id))]

    def add_images(self, args):
        style_id, role, items = required(args, "style_id"), required(args, "role"), required(args, "images", list)
        if role not in {"display", "recognition"}:
            raise ValueError("role 只能是 display 或 recognition")
        if not 1 <= len(items) <= 20:
            raise ValueError("每次添加 1～20 张图片")
        if self.library.get(style_id, True) is None:
            raise LookupError("款式不存在")
        results = []
        for index, item in enumerate(items):
            try:
                image = self.image(item)
                stream = BytesIO()
                image.save(stream, "PNG")
                source = item["image"] if isinstance(item, dict) else item
                filename = PurePosixPath(urllib.parse.urlsplit(source).path).name if source.startswith("http") else "ai-image.png"
                added = self.library.add_image(style_id, role, filename or "ai-image.png", stream.getvalue())
                results.append({"index": index, "ok": True, "imageId": added["image"]["id"], "duplicate": added["duplicate"]})
            except (ValueError, LookupError, OSError) as exc:
                results.append({"index": index, "ok": False, "error": str(exc)})
        return [text({"added": sum(r["ok"] and not r["duplicate"] for r in results),
                      "duplicates": sum(r["ok"] and r["duplicate"] for r in results),
                      "failed": sum(not r["ok"] for r in results), "results": results, "style": self.brief(style_id)})]

    def update_style_info(self, args):
        style_id, changes = required(args, "style_id"), self.info(args)
        if not changes:
            raise ValueError("至少提供 visual、params、notes 之一")
        with self.library.lock:
            style = self.library.get(style_id, True)
            if style is None:
                raise LookupError("款式不存在")
            self.library.update(style_id, {"info": {**style["info"], **changes}})
        return [text(self.brief(style_id))]

    def brief(self, style_id):
        style = self.library.get(style_id, True)
        return {key: style[key] for key in ("id", "name", "state", "missing", "displayCount", "recognitionCount",
                                            "pendingCount", "info")}
