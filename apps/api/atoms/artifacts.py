"""Parse and normalize the generator output before artifact validation."""
import json


def strict_json(raw):
    text=raw.strip()
    fence=chr(96)*3
    for marker in ("~~~",fence):
        if text.startswith(marker) and text.endswith(marker) and "\n" in text:
            text=text.split("\n",1)[1].rsplit(marker,1)[0].strip()
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:
                raise ValueError("重复 JSON 属性")
            result[key]=value
        return result
    return json.loads(text,object_pairs_hook=pairs,parse_constant=lambda _: (_ for _ in ()).throw(ValueError("非法数值")))


def normalize_artifact(artifact):
    """Fix unambiguous envelope mistakes before checking the full contract."""
    if type(artifact.get("schema_version")) is int and artifact["schema_version"] in (1,2):
        artifact["schema_version"]=str(artifact["schema_version"])
    if artifact.get("schema_version")=="2":
        return artifact
    files=artifact.get("files")
    if isinstance(files,dict):
        for name in ("index.html","styles.css","app.js"):
            if name not in files and isinstance(artifact.get(name),str):
                files[name]=artifact.pop(name)
    return artifact
