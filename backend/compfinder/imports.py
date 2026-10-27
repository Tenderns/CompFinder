import json
from pathlib import PurePosixPath

from .library import clean_info, clean_name, new_id

ROLES = {"展示图": "display", "识别图": "recognition"}
INFO_FILE = "款式信息.json"
# Chinese keys as written in the example file; the API's own keys are accepted too.
INFO_KEYS = {"参数": "params", "params": "params", "视觉信息": "visual", "visual": "visual", "备注": "notes", "notes": "notes"}


def unsafe(parts):
    return any(p in {"", ".", ".."} or "\\" in p or ":" in p or any(ord(c) < 32 for c in p) for p in parts)


def parse_path(raw):
    if not isinstance(raw, str) or len(raw) > 1000:
        raise ValueError("文件路径无效")
    filename = raw.rsplit("/", 1)[-1]
    if filename.startswith("款式信息") or PurePosixPath(filename).suffix.lower() == ".json":
        raise ValueError(f"款式信息文件须命名为“{INFO_FILE}”，直接放在款式文件夹内")
    parts = raw.split("/")
    if len(parts) not in {3, 4} or unsafe(parts):
        raise ValueError("目录应为 款式名称/展示图或识别图/图片，不能包含路径跳转")
    name, folder, filename = parts[-3:]
    if folder not in ROLES:
        raise ValueError("图片应放在“展示图”或“识别图”子目录")
    if PurePosixPath(filename).suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise ValueError("仅导入 JPG、PNG、WebP 图片")
    return clean_name(name), ROLES[folder]


def parse_info_path(raw):
    """款式名称/款式信息.json, optionally under one top-level folder."""
    parts = raw.split("/") if isinstance(raw, str) and len(raw) <= 1000 else []
    if len(parts) not in {2, 3} or unsafe(parts) or parts[-1].lower() != INFO_FILE or parts[-2] in ROLES:
        raise ValueError(f"“{INFO_FILE}”应直接放在款式文件夹内，与“展示图”“识别图”并列")
    return clean_name(parts[-2])


def info_text(value):
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (str, int, float)):
        return str(value)
    raise ValueError("每一项的内容应为文字、数字或由它们组成的列表")


def info_rows(value, label):
    """{名称: 内容} or [{"name", "value"}]; list contents are joined, null contents are dropped."""
    if value is None:
        return []
    if isinstance(value, dict):
        pairs = value.items()
    elif isinstance(value, list) and all(isinstance(item, dict) and "name" in item for item in value):
        pairs = [(item["name"], item.get("value")) for item in value]
    else:
        raise ValueError(f"“{label}”应写成 {{\"名称\": \"内容\"}} 的形式")
    rows = []
    for name, content in pairs:
        if content is None:
            continue
        if isinstance(content, list):
            content = "、".join(info_text(part) for part in content if part is not None)
        rows.append({"name": info_text(name), "value": info_text(content)})
    return rows


def parse_info(text):
    text = text.lstrip("﻿")
    if len(text) > 200_000:
        raise ValueError("款式信息文件过大")
    if "�" in text:
        raise ValueError("文件不是 UTF-8 编码，请用记事本“另存为”UTF-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"不是有效的 JSON：第 {exc.lineno} 行第 {exc.colno} 列附近有格式错误") from exc
    if not isinstance(data, dict):
        raise ValueError("文件内容应是一个以 { 开头的对象")
    info = {}
    for key, value in data.items():
        group = INFO_KEYS.get(key)
        if not group:
            raise ValueError(f"不支持“{key}”，只能填写“参数”“视觉信息”“备注”")
        if group in info:
            raise ValueError(f"“{key}”重复填写")
        if group != "notes":
            info[group] = info_rows(value, key)
        elif value is not None and not isinstance(value, str):
            raise ValueError("“备注”应为文字")
        else:
            info[group] = value or ""
    info = clean_info(info)
    if not (info["params"] or info["visual"] or info["notes"]):
        raise ValueError("文件中没有填写任何信息，已忽略")
    return info


class ImportManager:
    def __init__(self, library):
        self.library = library
        self.database = library.database

    def preview(self, paths, infos=None):
        """Group image paths by style; infos maps each 款式信息.json path to its text."""
        infos = infos or {}
        every = [*paths, *infos]
        if not every or len(every) > 20000 or len(set(every)) != len(every):
            raise ValueError("请选择 1～20000 个文件，文件路径不能重复")
        groups = {}
        rejected = []
        with self.database.connect() as db:
            def group(name):
                if name not in groups:
                    exists = bool(db.execute("SELECT 1 FROM styles WHERE name=? COLLATE NOCASE", (name,)).fetchone())
                    groups[name] = {"name": name, "displayCount": 0, "recognitionCount": 0,
                                    "skip": exists, "info": None, "infoPath": None, "files": []}
                return groups[name]
            for path in paths:
                try:
                    name, role = parse_path(path)
                    entry = group(name)
                    entry[f"{role}Count"] += 1
                    entry["files"].append({"path": path, "role": role})
                except ValueError as exc:
                    rejected.append({"path": path, "message": str(exc)})
            for path, text in infos.items():
                try:
                    name, info = parse_info_path(path), parse_info(text)
                    entry = group(name)
                    if entry["info"]:
                        raise ValueError("同一款式只能有一份款式信息")
                    entry.update(info=info, infoPath=path)
                except ValueError as exc:
                    rejected.append({"path": path, "message": str(exc)})
        return {"groups": list(groups.values()), "rejected": rejected}

    def create(self, paths, infos=None):
        job_id = new_id()
        with self.library.lock:
            preview = self.preview(paths, infos)
            with self.database.connect() as db:
                db.execute("INSERT INTO imports(id) VALUES (?)", (job_id,))
                for group in preview["groups"]:
                    style_id = None
                    info = json.dumps(group["info"], ensure_ascii=False) if group["info"] else "{}"
                    # Recheck under the write transaction; a concurrent creator may have used this name.
                    exists = db.execute("SELECT id FROM styles WHERE name=? COLLATE NOCASE", (group["name"],)).fetchone()
                    if not exists:
                        style_id = new_id()
                        db.execute("INSERT INTO styles(id,name,info) VALUES (?,?,?)", (style_id, group["name"], info))
                    if group["info"]:
                        # Images never merge into a same-name style, but its info is replaced by the file.
                        if exists:
                            db.execute("UPDATE styles SET info=? WHERE id=?", (info, exists["id"]))
                        db.execute("INSERT INTO import_files(job_id,path,style_id,style_name,role,state,message) VALUES (?,?,?,?,?,?,?)",
                                   (job_id, group["infoPath"], style_id or exists["id"], group["name"], "info", "info",
                                    "已更新同名款式的信息" if exists else "已写入款式信息"))
                    for item in group["files"]:
                        db.execute("INSERT INTO import_files(job_id,path,style_id,style_name,role,state,message) VALUES (?,?,?,?,?,?,?)",
                                   (job_id, item["path"], style_id, group["name"], item["role"], "skipped" if exists else "pending",
                                    "已有同名款式，未覆盖" if exists else None))
                for item in preview["rejected"]:
                    db.execute("INSERT INTO import_files(job_id,path,style_name,state,message) VALUES (?,?,?,?,?)",
                               (job_id, item["path"], "", "skipped", item["message"]))
        return self.get(job_id)

    def get(self, job_id):
        with self.database.connect() as db:
            job = db.execute("SELECT * FROM imports WHERE id=?", (job_id,)).fetchone()
            if not job:
                raise LookupError("导入任务不存在")
            items = [dict(r) for r in db.execute("SELECT path,style_id AS styleId,style_name AS styleName,role,state,message "
                                                "FROM import_files WHERE job_id=? ORDER BY rowid", (job_id,))]
        counts = {state: sum(item["state"] == state for item in items) for state in ("pending", "uploaded", "duplicate", "failed", "skipped", "info")}
        return {"id": job_id, "state": job["state"], "createdAt": job["created_at"], "counts": counts, "total": len(items), "files": items}

    def upload(self, job_id, path, data):
        with self.library.lock:
            with self.database.connect() as db:
                item = db.execute("SELECT f.*,j.state AS job_state FROM import_files f JOIN imports j ON j.id=f.job_id "
                                  "WHERE f.job_id=? AND f.path=?", (job_id, path)).fetchone()
            if not item:
                raise LookupError("此文件不在导入清单中")
            if item["job_state"] != "uploading":
                raise ValueError("导入任务已结束，请在款式管理中补充图片")
            if item["state"] != "pending":
                return {"path": path, "state": item["state"], "message": item["message"]}
            try:
                result = self.library.add_image(item["style_id"], item["role"], PurePosixPath(path).name, data)
                state, message = ("duplicate", "同一图片集中已有相同图片") if result["duplicate"] else ("uploaded", None)
            except (ValueError, LookupError, OSError) as exc:
                state, message = "failed", str(exc)[:300]
            with self.database.connect() as db:
                db.execute("UPDATE import_files SET state=?,message=? WHERE job_id=? AND path=?", (state, message, job_id, path))
        return {"path": path, "state": state, "message": message}

    def finish(self, job_id):
        with self.library.lock, self.database.connect() as db:
            if not db.execute("SELECT 1 FROM imports WHERE id=?", (job_id,)).fetchone():
                raise LookupError("导入任务不存在")
            db.execute("UPDATE import_files SET state='failed',message='文件未完成上传，请在对应款式中补图' "
                       "WHERE job_id=? AND state='pending'", (job_id,))
            db.execute("UPDATE imports SET state='complete' WHERE id=?", (job_id,))
        return self.get(job_id)
