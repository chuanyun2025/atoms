"""Built-in slide templates shared by the web preview and the generation worker."""

import json
from functools import cache

from atoms import SHARED_ROOT

_CATALOG = SHARED_ROOT / "slide-templates.json"


@cache
def _templates():
    items = json.loads(_CATALOG.read_text(encoding="utf-8"))
    return {item["id"]: item for item in items}


def slide_template_reference(template_id: str | None) -> dict | None:
    template = _templates().get(template_id) if template_id else None
    if template is None:
        return None
    return {
        "id": template["id"],
        "name": template["name"],
        "theme": template["theme"],
        "palette": template["palette"],
        "design": template["design"],
        "layout_sequence": [{"layout": page["layout"], "design": page["notes"]} for page in template["slides"]],
    }
