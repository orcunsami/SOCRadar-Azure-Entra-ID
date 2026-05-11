#!/usr/bin/env python3
"""
Analyze SOCRadar API responses.

For each *.json in responses/, infer field schema (name → type), record count,
and produce a sanitized schema file in schemas/ (no real data, just shape).

Usage:
    python3 analyze_response.py
    python3 analyze_response.py --source botnet --env preprod
"""

import json
import argparse
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).parent
RESPONSES_DIR = SCRIPT_DIR / "responses"
SCHEMAS_DIR = SCRIPT_DIR / "schemas"
SCHEMAS_DIR.mkdir(exist_ok=True)


def type_of(v: Any) -> str:
    """Return a short type label for a JSON value."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        if not v:
            return "list[empty]"
        inner = type_of(v[0])
        return f"list[{inner}]"
    if isinstance(v, dict):
        return "object"
    return type(v).__name__


def infer_schema(records: list) -> dict:
    """Infer field schema across all records. Returns {field_name: {type, example, null_pct}}."""
    schema: dict = {}
    n = len(records)
    if n == 0:
        return schema

    for rec in records:
        if not isinstance(rec, dict):
            continue
        for k, v in rec.items():
            if k not in schema:
                schema[k] = {"types": set(), "null_count": 0, "example": None}
            t = type_of(v)
            schema[k]["types"].add(t)
            if v is None or v == "":
                schema[k]["null_count"] += 1
            elif schema[k]["example"] is None and t != "null":
                # Save a sanitized example
                if isinstance(v, str):
                    if "@" in v:
                        schema[k]["example"] = "<email>"
                    elif len(v) > 30:
                        schema[k]["example"] = f"<{t}, len={len(v)}>"
                    else:
                        schema[k]["example"] = v if len(v) < 20 else f"<{t}>"
                elif isinstance(v, (int, float, bool)):
                    schema[k]["example"] = v
                elif isinstance(v, dict):
                    schema[k]["example"] = f"<object, keys={list(v.keys())[:5]}>"
                elif isinstance(v, list):
                    schema[k]["example"] = f"<list, len={len(v)}>"

    # Format output
    out = {}
    for k, info in schema.items():
        types = sorted(info["types"])
        null_pct = round(info["null_count"] / n * 100, 1) if n else 0
        out[k] = {
            "type": types[0] if len(types) == 1 else "|".join(types),
            "null_pct": null_pct,
            "example": info["example"],
        }
    return out


def analyze_file(path: Path) -> dict:
    """Analyze one response file."""
    try:
        d = json.load(open(path))
    except Exception as e:
        return {"error": f"Failed to parse: {e}"}

    data_obj = d.get("data", {}) or {}
    records = data_obj.get("data", []) if isinstance(data_obj, dict) else []

    return {
        "file": path.name,
        "envelope": {
            "is_success": d.get("is_success"),
            "message": d.get("message", "")[:50],
            "envelope_keys": sorted(d.keys()),
        },
        "data_keys": sorted(data_obj.keys()) if isinstance(data_obj, dict) else [],
        "total_data_count": data_obj.get("total_data_count") if isinstance(data_obj, dict) else None,
        "records_in_response": len(records),
        "record_schema": infer_schema(records),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["botnet", "pii", "vip"], help="Filter by source")
    parser.add_argument("--env", choices=["preprod", "platform"], help="Filter by env")
    args = parser.parse_args()

    files = sorted(RESPONSES_DIR.glob("*.json"))
    if args.source:
        files = [f for f in files if args.source in f.stem]
    if args.env:
        files = [f for f in files if args.env in f.stem]

    if not files:
        print(f"No response files in {RESPONSES_DIR}. Run run_all.sh first.")
        return

    summary = {}
    for path in files:
        result = analyze_file(path)
        print(f"\n========================================")
        print(f"  {path.name}")
        print(f"========================================")
        if "error" in result:
            print(f"  ERROR: {result['error']}")
            continue

        env = result["envelope"]
        print(f"  is_success: {env['is_success']}")
        print(f"  message: {env['message']}")
        print(f"  envelope_keys: {env['envelope_keys']}")
        print(f"  data_keys: {result['data_keys']}")
        print(f"  total_data_count: {result['total_data_count']}")
        print(f"  records_in_response: {result['records_in_response']}")
        print(f"  field schema ({len(result['record_schema'])} fields):")
        for fname, finfo in sorted(result["record_schema"].items()):
            null_marker = f" ({finfo['null_pct']}% null)" if finfo['null_pct'] > 0 else ""
            ex_marker = f" e.g. {finfo['example']!r}" if finfo['example'] is not None else ""
            print(f"    {fname:30s} : {finfo['type']:30s}{null_marker}{ex_marker}")

        # Save sanitized schema
        schema_path = SCHEMAS_DIR / f"{path.stem}.schema.json"
        with open(schema_path, "w") as f:
            json.dump({
                "envelope": result["envelope"],
                "data_keys": result["data_keys"],
                "total_data_count": result["total_data_count"],
                "records_in_response": result["records_in_response"],
                "record_schema": result["record_schema"],
            }, f, indent=2, default=str)
        summary[path.stem] = result

    print(f"\n========================================")
    print(f"  Schemas saved to {SCHEMAS_DIR}/")
    print(f"========================================")


if __name__ == "__main__":
    main()
