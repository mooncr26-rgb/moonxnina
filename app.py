import os
import threading
import uuid
import requests
import re
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app)

TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads_temp")
os.makedirs(TEMP_DIR, exist_ok=True)

download_tasks = {}

# YouTube ალტერნატივები
INVIDIOUS_INSTANCES = [
    "https://invidious.io.lol",
    "https://yewtu.be",
    "https://iv.melmac.space"
]

def get_clean_youtube_id(url):
    if "youtu.be/" in url: return url.split("youtu.be/")[-1].split("?")[0]
    if "v=" in url: return url.split("v=")[-1].split("&")[0]
    return None

def download_tiktok_fallback(url, local_filename):
    """ ალტერნატიული გზა ტიკტოკის ბლოკის ასავლელად (TikWM API) """
    try:
        api_url = "https://www.tikwm.com/api/"
        res = requests.post(api_url, data={'url': url}).json()
        if res.get('code') == 0:
            video_url = res['data']['play'] # ვიდეო ლოგოს (Watermark) გარეშე!
            video_bytes = requests.get(video_url, timeout=30).content
            with open(local_filename, 'wb') as f:
                f.write(video_bytes)
            return res['data'].get('title', 'TikTok_Video')
    except Exception as e:
        print(f"TikTok Fallback Error: {e}")
    return None

def background_download(url, file_type, task_id):
    try:
        ext = "mp3" if file_type == 'mp3' else "mp4"
        local_filename = os.path.join(TEMP_DIR, f"{task_id}.{ext}")
        
        # 👑 თუ ლინკი ტიკტოკისაა, პირდაპირ ვიყენებთ დაზღვეულ API-ს
        if "tiktok.com" in url:
            title = download_tiktok_fallback(url, local_filename)
            if title:
                download_tasks[task_id]['status'] = 'completed'
                download_tasks[task_id]['filename'] = local_filename
                download_tasks[task_id]['title'] = title
                return
            else:
                raise Exception("ტიკტოკის სერვერმა უარი თქვა ფაილის მოცემაზე.")

        # 🎥 სხვა პლატფორმებისთვის (YouTube და ა.შ.) ძველი ლოგიკა yt-dlp-ით
        opts = {
            'quiet': True,
            'nocheckcertificate': True,
            'outtmpl': os.path.join(TEMP_DIR, f"{task_id}.%(ext)s"),
            'format': 'bestaudio/best' if file_type == 'mp3' else 'best[ext=mp4]/best'
        }
        
        ffmpeg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ffmpeg')
        if os.path.exists(os.path.join(ffmpeg_path, 'ffmpeg')):
            opts['ffmpeg_location'] = ffmpeg_path
            
        if file_type == 'mp3':
            opts['postprocessors'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'}]

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                if file_type == 'mp3': filename = filename.rsplit('.', 1)[0] + '.mp3'
                
                download_tasks[task_id]['status'] = 'completed'
                download_tasks[task_id]['filename'] = filename
                download_tasks[task_id]['title'] = info.get('title', 'Downloaded_Media')
                return
        except Exception as ydl_err:
            # YouTube-ის გადაზღვევა
            yt_id = get_clean_youtube_id(url)
            if yt_id:
                for instance in INVIDIOUS_INSTANCES:
                    try:
                        inv_url = f"{instance}/latest_version?id={yt_id}&itype=mp4" if file_type == 'mp4' else f"{instance}/latest_version?id={yt_id}&itype=audio"
                        response = requests.get(inv_url, stream=True, timeout=30)
                        if response.status_code == 200:
                            with open(local_filename, 'wb') as f:
                                for chunk in response.iter_content(chunk_size=8192): f.write(chunk)
                            download_tasks[task_id]['status'] = 'completed'
                            download_tasks[task_id]['filename'] = local_filename
                            download_tasks[task_id]['title'] = f"YouTube_{yt_id}"
                            return
                    except: continue
            raise ydl_err

    except Exception as e:
        download_tasks[task_id]['status'] = 'failed'
        download_tasks[task_id]['error'] = str(e)

@app.route('/')
def index():
    return send_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'index.html'))

@app.route('/api/analyze', methods=['POST'])
def analyze_video():
    data = request.json or {}
    url = data.get('url', '')
    if not url: return jsonify({"error": "ბმული აკლია"}), 400
    
    if "tiktok.com" in url:
        return jsonify({"title": "TikTok ვიდეო (Watermark-ის გარეშე)"})
    
    yt_id = get_clean_youtube_id(url)
    if yt_id: return jsonify({"title": f"YouTube ვიდეო ({yt_id})"})
        
    return jsonify({"title": "მედია ფაილი მზად არის გადმოსაწერად"})

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
    
    # ფაილის უსაფრთხო დასახელება ჩამოსატვირთად
    safe_title = "".join([c for c in task['title'] if c.isalpha() or c.isdigit() or c==' ']).rstrip()
    ext = task['filename'].split('.')[-1]
    download_name = f"{safe_title or 'media'}.{ext}"
    
    return send_file(task['filename'], as_attachment=True, download_name=download_name)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
