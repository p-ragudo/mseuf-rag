import httpx

url = "https://mseuf.edu.ph/programs/lucena/bsit-cn"

response = httpx.get(url, timeout=10)
print(response.status_code)

with open("test_page.html", "w", encoding="utf-8") as f:
    f.write(response.text)

print("Saved. Open test_page.html and look for the data-page attribute.")