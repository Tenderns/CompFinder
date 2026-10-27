"""ytst tactile switch taxonomy v1.1: visual fields are what AI may write into 视觉信息."""
import json
from pathlib import Path

TAXONOMY = json.loads(Path(__file__).with_name("tactile_taxonomy_v1_1.json").read_text(encoding="utf-8"))
FIELDS = TAXONOMY["fields"]
VISUAL = {field["label"]: field for field in FIELDS.values() if field.get("visual")}
SPECS = {field["label"]: field for field in FIELDS.values() if not field.get("visual")}


def allowed(field):
    kind = field["type"]
    if kind in {"enum", "multi_enum"}:
        text = " / ".join(field["choices"].values())
        return f"{text}（可多选，用列表）" if kind == "multi_enum" else text
    unit = f"，单位 {field['unit']}" if field.get("unit") and field["unit"] != "个" else ""
    return {"boolean": "是 / 否", "integer": "整数", "number": f"数字{unit}"}.get(kind, f"文字{unit}")


def describe():
    labels = {key: field["label"] for key, field in FIELDS.items()}
    lines = [f"{TAXONOMY['title']}（{TAXONOMY['version']}）。{TAXONOMY['notice']}",
             "视觉信息只填照片里能确认的字段，看不清或不确定就省略，不要填“未知”。", "", "优先填写的 8 组关键结构："]
    lines += [f"- {group['label']}：{'、'.join(labels[key] for key in group['fields'])}" for group in TAXONOMY["searchProfile"]["groups"]]
    lines += ["", "视觉信息字段（名称：可选值）："]
    lines += [f"- {label}：{allowed(field)}" for label, field in VISUAL.items()]
    lines += ["", "参数字段（来自页面或资料，名称建议用以下规范名）："]
    lines += [f"- {label}：{allowed(field)}" for label, field in SPECS.items()]
    return "\n".join(lines)


def check_visual(rows):
    """Reject names and values outside the taxonomy so every style uses the same vocabulary."""
    problems = []
    for row in rows:
        name, value = row["name"], row["value"]
        field = VISUAL.get(name)
        if field is None:
            problems.append(f"“{name}”不是规范中的视觉字段")
            continue
        choices = list(field.get("choices", {}).values())
        kind = field["type"]
        if not value:
            problems.append(f"“{name}”没有内容；不确定的字段请直接省略")
        elif kind == "enum" and value not in choices:
            problems.append(f"“{name}”只能是 {' / '.join(choices)}")
        elif kind == "multi_enum" and not all(part in choices for part in value.split("、")):
            problems.append(f"“{name}”只能从 {' / '.join(choices)} 中选择")
        elif kind == "boolean" and value not in {"是", "否"}:
            problems.append(f"“{name}”只能是 是 / 否")
        elif kind == "integer" and not value.isdigit():
            problems.append(f"“{name}”应为整数")
        elif kind == "number":
            try:
                float(value)
            except ValueError:
                problems.append(f"“{name}”应为数字")
    if problems:
        raise ValueError("视觉信息不符合 ytst 规范 v1.1：" + "；".join(problems) + "。可调用 visual_taxonomy 查看字段和可选值")
