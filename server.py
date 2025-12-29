from api import APIBlueprint
from werkzeug.middleware.proxy_fix import ProxyFix
from flask import Flask, Response, send_from_directory
from storage import relpath
import os

app = Flask(__name__, static_folder=relpath("static"), static_url_path="/static")
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1)

# Register static file routes BEFORE blueprint
# Handle /static/ and /jnd/static/ paths
@app.route("/static/<path:filename>")
@app.route("/jnd/static/<path:filename>")
def static_files(filename):
    """Serve static files from the static directory"""
    static_dir = relpath("static")
    file_path = os.path.join(static_dir, filename)
    if os.path.exists(file_path) and os.path.isfile(file_path):
        return send_from_directory(static_dir, filename)
    return Response("File not found", status=404)

app.register_blueprint(APIBlueprint())

@app.route("/favicon.ico")
def favicon():
    return Response(status=204)

if __name__ == "__main__":
    app.run(host="unix:///tmp/audio.experiments.api.sock")

