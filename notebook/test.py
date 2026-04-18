from curl_cffi import requests

def fetch(chapter):
    url = f"https://manhuaus.com/manga/star-embracing-swordmaster/chapter-{chapter}/"
    r = requests.get(url, impersonate="chrome136",
                     headers={"referer": "https://manhuaus.com/"})
    print(f"Ch.{chapter}: len={len(r.text)}")
    # ดู title
    start = r.text.find("<title>")
    end = r.text.find("</title>")
    if start > -1:
        print(f"  title: {r.text[start+7:end][:100]}")
    # เช็คว่ามี manga images ไหม
    img_count = r.text.count("<img")
    print(f"  img tags: {img_count}")
    # เช็ค keywords ที่บ่งบอกว่า chapter ไม่มี
    for kw in ["not found", "404", "not available", "does not exist", "no chapters"]:
        if kw in r.text.lower():
            print(f"  found keyword: '{kw}'")

fetch(118)       # มีจริง
fetch(10000000)  # ไม่มี