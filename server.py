from api import APIBlueprint
from api_review import ReviewAPIBlueprint
from werkzeug.middleware.proxy_fix import ProxyFix
from flask import Flask, Response, redirect, send_from_directory
from storage import relpath
import os

app = Flask(__name__, static_folder=relpath("static"), static_url_path="/static")
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1)

# Enable CORS headers on all responses to allow cross-origin fetching of data
@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    return response

# Handle OPTIONS preflight requests globally
@app.route('/', defaults={'path': ''}, methods=['OPTIONS'])
@app.route('/<path:path>', methods=['OPTIONS'])
def handle_options(path):
    response = Response(status=200)
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    return response

# Serve quicksin_results.csv at root and ~mslaney routes
@app.route("/quicksin_results.csv")
@app.route("/~mslaney/quicksin_results.csv")
def serve_quicksin_csv():
    csv_path = relpath("quicksin_results.csv")
    if os.path.exists(csv_path):
        return send_from_directory(os.path.dirname(csv_path), os.path.basename(csv_path))
    return Response("CSV file not found", status=404)

# Register static file routes BEFORE blueprint
# Handle /static/, /jnd/static/, and /jnd/api/static/ paths
@app.route("/static/<path:filename>")
@app.route("/jnd/static/<path:filename>")
@app.route("/jnd/api/static/<path:filename>")
def static_files(filename):
    """Serve static files from the static directory"""
    static_dir = relpath("static")
    file_path = os.path.join(static_dir, filename)
    if os.path.exists(file_path) and os.path.isfile(file_path):
        # For PDFs, explicitly read in binary mode to prevent corruption
        if filename.lower().endswith('.pdf'):
            with open(file_path, 'rb') as f:
                pdf_data = f.read()
            response = Response(pdf_data, mimetype='application/pdf')
            response.headers['Content-Disposition'] = f'inline; filename="{os.path.basename(filename)}"'
            return response
        else:
            return send_from_directory(static_dir, filename)
    return Response("File not found", status=404)

app.register_blueprint(APIBlueprint())
app.register_blueprint(ReviewAPIBlueprint())

#prevent 404
@app.route("/favicon.ico")
def favicon():
    return Response(status=204)

if __name__ == "__main__":
    app.run(host="unix:///tmp/audio.experiments.api.sock")

