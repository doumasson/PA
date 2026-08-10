import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

HTML = '<!DOCTYPE html>\n<html>\n<head><title>Albus - Connect Bank</title>\n<style>\nbody { font-family: Arial, sans-serif; max-width: 600px; margin: 100px auto; text-align: center; }\nbutton { background: #4F46E5; color: white; border: none; padding: 16px 32px; font-size: 18px; border-radius: 8px; cursor: pointer; }\n#result { margin-top: 20px; padding: 20px; background: #f0fdf4; border-radius: 8px; display: none; }\n</style>\n</head>\n<body>\n<h1>Connect Your Bank</h1>\n<button id="btn">Connect Wells Fargo</button>\n<div id="result"><h2>Connected!</h2><p id="token-display"></p></div>\n<script src="https://cdn.teller.io/connect/connect.js"></script>\n<script>\nvar APP_ID = "app_pq79sg29r572k1h1sm000";\ndocument.getElementById("btn").addEventListener("click", function() {\n  var teller = TellerConnect.setup({\n    applicationId: APP_ID,\n    environment: "development",\n    products: ["balance", "transactions"],\n    onSuccess: function(enrollment) {\n      document.getElementById("token-display").textContent = enrollment.accessToken;\n      document.getElementById("result").style.display = "block";\n      fetch("/token", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(enrollment)});\n    },\n    onExit: function() {}\n  });\n  teller.open();\n});\n</script>\n</body>\n</html>'
enrollment_result = {}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, f, *a): pass
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(HTML.encode())
    def do_POST(self):
        if self.path == "/token":
            length = int(self.headers["Content-Length"])
            data = json.loads(self.rfile.read(length))
            enrollment_result.update(data)
            print("\nTOKEN:", data.get("accessToken"))
            self.send_response(200)
            self.end_headers()
            threading.Thread(target=lambda: server.shutdown()).start()

server = HTTPServer(("0.0.0.0", 8765), Handler)
print("Open: http://192.168.1.172:8765")
server.serve_forever()
if enrollment_result:
    print("ACCESS TOKEN:", enrollment_result.get("accessToken"))
