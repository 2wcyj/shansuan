import http.cookiejar
import json
import urllib.request

opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),urllib.request.ProxyHandler({}))
try:
    data = json.load(opener.open('http://127.0.0.1:18765/api/session',timeout=3))
    req = urllib.request.Request('http://127.0.0.1:18765/api/shutdown',data=b'{}',headers={'Content-Type':'application/json','X-CSRF-Token':data['csrf']})
    opener.open(req,timeout=3).close()
    print('应用已停止。')
except OSError:
    print('没有发现正在运行的应用。')
