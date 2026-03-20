from flask import Flask, jsonify, send_file
from flask_cors import CORS
import subprocess
import os
from datetime import datetime

app = Flask(__name__)
CORS(app)

@app.route('/')
def home():
    return jsonify({
        "name": "Wheel Strategy Scanner API",
        "version": "1.0",
        "endpoints": {
            "GET /": "API information",
            "GET /scan": "Run scanner and return results",
            "GET /download": "Download latest CSV file",
            "GET /health": "Health check"
        }
    })

@app.route('/health')
def health():
    return jsonify({"status": "healthy"})

@app.route('/scan')
def scan():
    try:
        # Run the scanner script
        result = subprocess.run(
            ['python', 'scanner.py'],
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )
        
        # Check if CSV was created
        csv_files = [f for f in os.listdir('.') if f.endswith('.csv')]
        
        if csv_files:
            latest_csv = max(csv_files, key=os.path.getctime)
            return jsonify({
                "status": "success",
                "message": "Scan completed",
                "csv_file": latest_csv,
                "download_url": f"/download?file={latest_csv}",
                "output": result.stdout[:1000]  # First 1000 chars
            })
        else:
            return jsonify({
                "status": "success",
                "message": "Scan completed but no CSV generated",
                "output": result.stdout[:1000]
            })
    
    except subprocess.TimeoutExpired:
        return jsonify({
            "status": "error",
            "error": "Scanner timed out after 5 minutes"
        }), 500
    
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500

@app.route('/download')
def download():
    try:
        from flask import request
        filename = request.args.get('file')
        
        if not filename or not filename.endswith('.csv'):
            return jsonify({"error": "Invalid filename"}), 400
        
        if not os.path.exists(filename):
            return jsonify({"error": "File not found"}), 404
        
        return send_file(filename, as_attachment=True)
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
