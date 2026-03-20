from flask import Flask, jsonify, send_file, Response, stream_with_context, send_from_directory
from flask_cors import CORS
import subprocess
import os

app = Flask(__name__)
CORS(app)

scan_running = False

@app.route('/')
def home():
    return send_from_directory('.', 'index.html')

@app.route('/api')
def api_info():
    return jsonify({
        "name": "Wheel Strategy Scanner API",
        "version": "1.0",
        "endpoints": {
            "GET /": "Web interface",
            "GET /api": "API information",
            "GET /scan": "Run scanner (JSON response)",
            "GET /scan/stream": "Run scanner with real-time progress",
            "GET /status": "Check if scan is running",
            "GET /download": "Download latest CSV file",
            "GET /health": "Health check"
        }
    })

@app.route('/health')
def health():
    return jsonify({"status": "healthy"})

@app.route('/status')
def status():
    return jsonify({
        "scanning": scan_running,
        "message": "Scan in progress..." if scan_running else "No scan running"
    })

@app.route('/scan')
def scan():
    global scan_running
    
    if scan_running:
        return jsonify({
            "status": "busy",
            "message": "A scan is already running. Please wait."
        }), 429
    
    try:
        scan_running = True
        
        print("Starting scanner...")
        result = subprocess.run(
            ['python', 'scanner.py'],
            capture_output=True,
            text=True,
            timeout=600
        )
        
        scan_running = False
        
        csv_files = [f for f in os.listdir('.') if f.endswith('.csv')]
        
        if csv_files:
            latest_csv = max(csv_files, key=os.path.getctime)
            file_size = os.path.getsize(latest_csv)
            
            return jsonify({
                "status": "success",
                "message": "Scan completed successfully",
                "csv_file": latest_csv,
                "file_size_kb": round(file_size / 1024, 2),
                "download_url": f"/download?file={latest_csv}",
                "preview": result.stdout[-500:] if result.stdout else "No output"
            })
        else:
            return jsonify({
                "status": "completed",
                "message": "Scan completed but no CSV generated",
                "output": result.stdout[-500:] if result.stdout else "No output"
            })
    
    except subprocess.TimeoutExpired:
        scan_running = False
        return jsonify({
            "status": "error",
            "error": "Scanner timed out after 10 minutes"
        }), 500
    
    except Exception as e:
        scan_running = False
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500

@app.route('/scan/stream')
def scan_stream():
    global scan_running
    
    if scan_running:
        return jsonify({
            "status": "busy",
            "message": "A scan is already running"
        }), 429
    
    def generate():
        global scan_running
        scan_running = True
        
        try:
            process = subprocess.Popen(
                ['python', 'scanner.py'],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            yield 'data: {"status": "started", "message": "Scanner started..."}\n\n'
            
            for line in iter(process.stdout.readline, ''):
                if line:
                    safe_line = line.strip().replace('"', '\\"')
                    yield f'data: {{"status": "progress", "message": "{safe_line}"}}\n\n'
            
            process.wait()
            
            csv_files = [f for f in os.listdir('.') if f.endswith('.csv')]
            
            if csv_files:
                latest_csv = max(csv_files, key=os.path.getctime)
                yield f'data: {{"status": "success", "csv_file": "{latest_csv}", "download_url": "/download?file={latest_csv}"}}\n\n'
            else:
                yield 'data: {"status": "completed", "message": "No CSV generated"}\n\n'
        
        except Exception as e:
            error_msg = str(e).replace('"', '\\"')
            yield f'data: {{"status": "error", "error": "{error_msg}"}}\n\n'
        
        finally:
            scan_running = False
    
    return Response(stream_with_context(generate()), mimetype='text/event-stream')

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
    print(f"Starting Wheel Scanner API on port {port}...")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)