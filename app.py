import os
import threading
import uuid
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app)

TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads_temp")
os.makedirs(TEMP_DIR, exist_ok=True)

download_tasks = {}

def ydl_progress_hook(d, task_id):
    if d['status'] == 'downloading':
        total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
        downloaded = d.get('downloaded_bytes', 0)
        if total > 0:
            percent = int((downloaded / total) * 100)
            download_tasks[task_id]['progress'] = percent
    elif d['status'] == 'finished':
        download_tasks[task_id]['progress'] = 100

def background_download(url, file_type, task_id):
    try:
        outtmpl = os.path.join(TEMP_DIR, f"{task_id}.%(ext)s")
        ffmpeg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ffmpeg')
        
        # 🛡️ გაძლიერებული პარამეტრები YouTube-ის ბლოკირების ასავლელად
        opts = {
            'quiet': True,
            'nocheckcertificate': True,
            'outtmpl': outtmpl,
            'progress_hooks': [lambda d: ydl_progress_hook(d, task_id)],
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web'],
                    'player_skip': ['configs', 'initial'],
                }
            },
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
            }
        }
        
        # თუ cookies.txt ფაილს ატვირთავ, კოდი მასაც ავტომატურად გამოიყენებს
        cookies_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cookies.txt')
        if os.path.exists(cookies_file):
            opts['cookiefile'] = cookies_file
        
        if os.path.exists(os.path.join(ffmpeg_path, 'ffmpeg')):
            opts['ffmpeg_location'] = ffmpeg_path
        
        if file_type == 'mp3':
            opts['format'] = 'bestaudio/best'
            opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320'
            }]
        else:
            opts['format'] = 'best[ext=mp4]/best'

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if file_type == 'mp3':
                filename = filename.rsplit('.', 1)[0] + '.mp3'
            
            download_tasks[task_id]['status'] = 'completed'
            download_tasks[task_id]['filename'] = filename
            download_tasks[task_id]['title'] = info.get('title', 'MOONXNINA_Media')
            
    except Exception as e:
        download_tasks[task_id]['status'] = 'failed'
        download_tasks[task_id]['error'] = str(e)

@app.route('/')
def index():
    return send_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'index.html'))

@app.route('/api/analyze', methods=['POST'])
def analyze_video():
    data = request.json or {}
    url = data.get('url')
    if not url: return jsonify({"error": "ბმული აკლია"}), 400
    
    # ანალიზისთვისაც ვამატებთ ბლოკის საწინააღმდეგო იდენტურ პარამეტრებს
    analyze_opts = {
        'quiet': True, 
        'nocheckcertificate': True,
        'extractor_args': {'youtube': {'player_client': ['android', 'web'], 'player_skip': ['configs', 'initial']}}
    }
    cookies_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cookies.txt')
    if os.path.exists(cookies_file):
        analyze_opts['cookiefile'] = cookies_file

    try:
        with yt_dlp.YoutubeDL(analyze_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return jsonify({"title": info.get('title', 'ვიდეო ხელმისაწვდომია')})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/download', methods=['POST'])
def start_download():
    data = request.json or {}
    url = data.get('url')
    file_type = data.get('type')
    
    if not url: return jsonify({"error": "ბმული აკლია"}), 400
    
    task_id = str(uuid.uuid4())
    download_tasks[task_id] = {'progress': 0, 'status': 'processing', 'filename': ''}
    
    thread = threading.Thread(target=background_download, args=(url, file_type, task_id))
    thread.start()
    
    return jsonify({"task_id": task_id})

@app.route('/api/progress/<task_id>', methods=['GET'])
def get_progress(task_id):
    task = download_tasks.get(task_id)
    if not task: return jsonify({"error": "პროცესი ვერ მოიძებნა"}), 404
    return jsonify(task)

@app.route('/api/get_file/<task_id>', methods=['GET'])
def get_file(task_id):
    task = download_tasks.get(task_id)
    if not task or task['status'] != 'completed':
        return "ფაილი ჯერ არ არის მზად", 400
    
    filepath = task['filename']
    ext = filepath.split('.')[-1]
    safe_title = "".join([c for c in task['title'] if c.isalpha() or c.isdigit() or c==' ']).rstrip()
    download_name = f"{safe_title or 'media'}.{ext}"
    
    return send_file(filepath, as_attachment=True, download_name=download_name)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
