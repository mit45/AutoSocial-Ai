import urllib.request, urllib.error

url = "http://127.0.0.1:9001/api/scheduled/check"
req = urllib.request.Request(
    url, data=b"{}", headers={"Content-Type": "application/json"}
)
try:
    with urllib.request.urlopen(req, timeout=60) as r:
        print("HTTP", r.status)
        print(r.read().decode("utf-8"))
except urllib.error.HTTPError as he:
    print("HTTPError", he.code)
    try:
        print(he.read().decode("utf-8"))
    except Exception:
        print(str(he))
except Exception as e:
    print("error", e)
