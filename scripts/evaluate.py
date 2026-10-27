"""Evaluate independent query photos against an existing library without modifying it."""
import argparse
import json
import os
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8010")
    parser.add_argument("--token", default=os.getenv("COMPFINDER_TOKEN"), help="Access token; defaults to COMPFINDER_TOKEN or data/access-token.txt")
    args = parser.parse_args()
    cases = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    if not isinstance(cases, list) or not cases:
        raise SystemExit("Manifest must be a nonempty list")
    results = []
    token = args.token
    if not token:
        token_file = Path(__file__).resolve().parents[1] / "data" / "access-token.txt"
        token = token_file.read_text(encoding="utf-8").strip() if token_file.is_file() else ""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with httpx.Client(base_url=args.url, timeout=120, headers=headers) as client:
        for case in cases:
            files = [("files", (Path(name).name, (args.manifest.parent / name).read_bytes())) for name in case["images"]]
            response = client.post("/api/search?limit=5", files=files)
            response.raise_for_status()
            candidates = response.json()["items"]
            ids = [r["id"] for r in candidates]
            results.append({"name": case["name"], "expectedStyleId": case["expectedStyleId"],
                            "top1": bool(ids and ids[0] == case["expectedStyleId"]),
                            "top5": case["expectedStyleId"] in ids,
                            "candidates": [{"id": r["id"], "name": r["name"], "similarity": r["similarity"]} for r in candidates]})
    report = {"queries": len(results), "top1": sum(r["top1"] for r in results) / len(results),
              "top5": sum(r["top5"] for r in results) / len(results), "results": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Queries: {len(results)}; Top-1: {report['top1']:.1%}; Top-5: {report['top5']:.1%}")


if __name__ == "__main__":
    main()
