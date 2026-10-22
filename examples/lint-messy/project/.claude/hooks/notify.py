import json, sys

payload = json.load(sys.stdin)
path = payload.get("tool_input", {}).get("file_path", "")
if path.endswith(".py"):
    print(f"reminder: run the tests for {path}")
