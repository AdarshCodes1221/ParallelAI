import urllib.request, urllib.parse
url='http://127.0.0.1:8000/api/agent'
data=urllib.parse.urlencode({'query':'Please summarize this document.'}).encode()
req=urllib.request.Request(url,data=data,method='POST')
with urllib.request.urlopen(req,timeout=30) as r:
    chunk=r.read(2048)
    print(chunk.decode(errors='ignore'))
