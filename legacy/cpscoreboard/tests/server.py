import http.server
import socketserver

PORT = 8000

Handler = http.server.SimpleHTTPRequestHandler

i = 0

with socketserver.TCPServer(("", PORT), Handler) as httpd:
    print("serving at port", PORT)
    httpd.serve_forever()

# copy testpage_orig.php to testpage.php
# for i in the length(list of pages)
# wait for a request and serve the page (testpage.php)
# copy "testpage" + i + ".php" to testpage.php