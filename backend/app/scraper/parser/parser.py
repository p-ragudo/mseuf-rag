import re
import json
import html

with open("test_page.html", "r", encoding="utf-8") as f:
    content = f.read()

match = re.search(r'data-page="([^"]+)"', content)
raw_json_str = html.unescape(match.group(1))
data = json.loads(raw_json_str)

print(data["props"]["program"]["title"])
print(data["props"]["program"]["curriculum"][1])