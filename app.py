import os
import threading
import uuid
import requests
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app)

TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads_temp")
os.makedirs(TEMP_DIR, exist_ok=True)

download_tasks = {}

def download_tiktok_fallback(url, local_filename):
    try:
        api_url = "https://www.tikwm.com/api/"
        res = requests.post(api_url, data={'url': url}).json()
        if res.get('code') == 0:
            video_url = res['data']['play']
            video_bytes = requests.get(video_url, timeout=30).content
            with open(local_filename, 'wb') as f:
                f.write(video_bytes)
            return res['data'].get('title', 'TikTok_Video')
    except Exception as e:
        print(f"TikTok Error: {e}")
    return None

def background_download(url, file_type, task_id):
    try:
        ext = "mp3" if file_type == 'mp3' else "mp4"
        local_filename = os.path.join(TEMP_DIR, f"{task_id}.{ext}")
        
        # 1. ტიკტოკის ჩამოტვირთვა
        if "tiktok.com" in url:
            title = download_tiktok_fallback(url, local_filename)
            if title:
                download_tasks[task_id]['status'] = 'completed'
                download_tasks[task_id]['filename'] = local_filename
                download_tasks[task_id]['title'] = title
                return
            else:
                raise Exception("TikTok სერვერი დროებით მიუწვდომელია.")

        # 2. YouTube ჩამოტვირთვა (გაძლიერებული ლოკალური კონვერტაციით)
        ffmpeg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ffmpeg')
        
        opts = {
            'quiet': True,
            'nocheckcertificate': True,
            'outtmpl': os.path.join(TEMP_DIR, f"{task_id}.%(ext)s"),
            # იყენებს კლიენტის სხვადასხვა იმიტაციას ბლოკის ასავლელად
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web'],
                    'player_skip': ['configs', 'initial'],
                }
            },
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
            }
        }

        if os.path.exists(os.path.join(ffmpeg_path, 'ffmpeg')):
            opts['ffmpeg_location'] = ffmpeg_path

        if file_type == 'mp3':
            # 👑 უმკაცრესი ინსტრუქცია FFmpeg-ისთვის: აიძულებს ფაილის რეალურ აუდიოდ გადაკეთებას
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
            
            # ვამოწმებთ, რომ FFmpeg-მა მართლა შეცვალა გაფართოება
            if file_type == 'mp3' and not filename.endswith('.mp3'):
                filename = filename.rsplit('.', 1)[0] + '.mp3'
                
            if os.path.exists(filename):
                download_tasks[task_id]['status'] = 'completed'
                download_tasks[task_id]['filename'] = filename
                download_tasks[task_id]['title'] = info.get('title', 'Media_File')
            else:
                raise Exception("ფაილის საბოლოო დამუშავება ვერ მოხერხდა.")

    except Exception as e:
        download_tasks[task_id]['status'] = 'failed'
        err_msg = str(e)
        if "Sign in to confirm" in err_msg or "429" in err_msg:
            download_tasks[task_id]['error'] = "YouTube ბლოკავს სერვერს. გთხოვთ ატვირთოთ cookies.txt რეპოზიტორიაში."
        else:
            download_tasks[task_id]['error'] = "დამუშავების შეცდომა. ხელახლა სცადეთ."

@app.route('/')
def index():
    return send_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'index.html'))

@app.route('/api/analyze', methods=['POST'])
def analyze_video():
    data = request.json or {}
    url = data.get('url', '')
    if not url: return jsonify({"error": "ბმული აკლია"}), 400
    if "tiktok.com" in url: return jsonify({"title": "TikTok ვიდეო"})
    return jsonify({"title": "მედია ფაილი ნაპოვნია"})

@app.route('/api/download', methods=['POST'])
def start_download():
    data = request.json or {}
    url = data.get('url')
    file_type = data.get('type')
    
    task_id = str(uuid.uuid4())
    download_tasks[task_id] = {'progress': 50, 'status': 'processing', 'filename': ''}
    
    thread = threading.Thread(target=background_download, args=(url, file_type, task_id))
    thread.start()
    return jsonify({"task_id": task_id})

@app.route('/api/progress/<task_id>', methods=['GET'])
def get_progress(task_id):
    task = download_tasks.get(task_id)
    if not task: return jsonify({"error": "ვერ მოიძებნა"}), 404
    return jsonify(task)

@app.route('/api/get_file/<task_id>', methods=['GET'])
def get_file(task_id):
    task = download_tasks.get(task_id)
    if not task or task['status'] != 'completed': return "არ არის მზად", 400
    
    safe_title = "".join([c for c in task['title'] if c.isalpha() or c.isdigit() or c==' ']).rstrip()
    ext = task['filename'].split('.')[-1]
    download_name = f"{safe_title or 'media'}.{ext}"
    
    return send_file(task['filename'], as_attachment=True, download_name=download_name)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
