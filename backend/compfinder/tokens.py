"""MCP access tokens, kept in the database so the web page can show, copy and edit them."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import secrets
import sqlite3

from .library import new_id


def digest(secret):
    return hashlib.sha256(secret.encode()).hexdigest()


def stamp(moment):
    # Same text form as SQLite's strftime('%Y-%m-%dT%H:%M:%fZ'), so stored times compare as strings.
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class TokenStore:
    def __init__(self, database, tool_names, login_token=None):
        self.database, self.tool_names, self.login_token = database, tuple(tool_names), login_token

    def serialize(self, row):
        granted = set(json.loads(row["tools"]))
        return {"id": row["id"], "name": row["name"], "secret": row["secret"],
                "tools": [name for name in self.tool_names if name in granted], "enabled": bool(row["enabled"]),
                "createdAt": row["created_at"], "lastUsedAt": row["last_used_at"]}

    def clean(self, changes):
        values = {}
        if "name" in changes:
            name = changes["name"].strip()
            if not name or len(name) > 60 or any(ord(char) < 32 for char in name):
                raise ValueError("名称须为 1～60 个字符")
            values["name"] = name
        if "tools" in changes:
            unknown = [name for name in changes["tools"] if name not in self.tool_names]
            if unknown:
                raise ValueError(f"未知工具：{'、'.join(unknown)}")
            if not changes["tools"]:
                raise ValueError("至少选择一个工具")
            values["tools"] = json.dumps([name for name in self.tool_names if name in changes["tools"]])
        if "enabled" in changes:
            values["enabled"] = int(bool(changes["enabled"]))
        if "secret" in changes:
            secret = changes["secret"].strip()
            if not 24 <= len(secret) <= 200 or not secret.isascii() or not secret.isprintable() or " " in secret:
                raise ValueError("令牌须为 24～200 个英文字母、数字或符号，不能有空格")
            if self.login_token and secret == self.login_token:
                raise ValueError("MCP 令牌不能与网页登录令牌相同")
            values.update(secret=secret, secret_hash=digest(secret))
        return values

    def list(self):
        with self.database.connect() as db:
            return [self.serialize(row) for row in db.execute("SELECT * FROM mcp_tokens ORDER BY created_at,id")]

    def get(self, token_id):
        with self.database.connect() as db:
            row = db.execute("SELECT * FROM mcp_tokens WHERE id=?", (token_id,)).fetchone()
        if row is None:
            raise LookupError("令牌不存在")
        return self.serialize(row)

    def create(self, name, tools, secret=None):
        values = self.clean({"name": name, "tools": tools, "secret": secret or secrets.token_urlsafe(32)})
        token_id = new_id()
        try:
            with self.database.connect() as db:
                db.execute("INSERT INTO mcp_tokens(id,name,secret,secret_hash,tools) VALUES (?,?,?,?,?)",
                           (token_id, values["name"], values["secret"], values["secret_hash"], values["tools"]))
        except sqlite3.IntegrityError as exc:
            raise ValueError("这个令牌已被使用，请换一个") from exc
        return self.get(token_id)

    def update(self, token_id, changes):
        values = self.clean(changes)
        try:
            with self.database.connect() as db:
                # Column names come only from clean(), never from the request.
                assignments = ",".join(f"{column}=?" for column in values) or "id=id"
                if not db.execute(f"UPDATE mcp_tokens SET {assignments} WHERE id=?", (*values.values(), token_id)).rowcount:
                    raise LookupError("令牌不存在")
        except sqlite3.IntegrityError as exc:
            raise ValueError("这个令牌已被使用，请换一个") from exc
        return self.get(token_id)

    def delete(self, token_id):
        with self.database.connect() as db:
            if not db.execute("DELETE FROM mcp_tokens WHERE id=?", (token_id,)).rowcount:
                raise LookupError("令牌不存在")

    def resolve(self, secret):
        """Tools an enabled token may use, or None when the secret matches no enabled token."""
        if not secret:
            return None
        with self.database.connect() as db:
            row = db.execute("SELECT * FROM mcp_tokens WHERE secret_hash=? AND enabled=1", (digest(secret),)).fetchone()
            if row is None:
                return None
            now = datetime.now(timezone.utc)
            # Record use at most once a minute so busy clients do not turn every call into a write.
            if not row["last_used_at"] or row["last_used_at"] < stamp(now - timedelta(minutes=1)):
                db.execute("UPDATE mcp_tokens SET last_used_at=? WHERE id=?", (stamp(now), row["id"]))
        return set(self.serialize(row)["tools"])
