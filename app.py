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

def get_clean_youtube_id(url):
    if "youtu.be/" in url: return url.split("youtu.be/")[-1].split("?")[0]
    if "v=" in url: return url.split("v=")[-1].split("&")[0]
    return None

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

def download_youtube_ultimate_fallback(yt_id, file_type, local_filename):
    """ 
    YouTube-ის ჩამოტვირთვის უახლესი გზა Piped API-სა და მრავალმხრივი გეითვეების გამოყენებით.
    """
    # 1. ვცდილობთ Piped API-ს (ეს არის ყველაზე სტაბილური ამჟამად)
    try:
        piped_res = requests.get(f"https://pipedapi.kavin.rocks/streams/{yt_id}", timeout=15).json()
        
        if file_type == "mp4" and "videoStreams" in piped_res:
            # ვეძებთ სასურველ ვიდეო სტრიმს, რომელსაც ხმაც მოჰყვება
            streams = [s for s in piped_res["videoStreams"] if s.get("videoOnly") is False]
            if not streams: streams = piped_res["videoStreams"]
            if streams:
                video_url = streams[0]["url"]
                r = requests.get(video_url, timeout=60)
                if r.status_code == 200:
                    with open(local_filename, 'wb') as f: f.write(r.content)
                    return True
                    
        elif file_type == "mp3" and "audioStreams" in piped_res:
            audio_url = piped_res["audioStreams"][0]["url"]
            r = requests.get(audio_url, timeout=60)
            if r.status_code == 200:
                with open(local_filename, 'wb') as f: f.write(r.content)
                return True
    except Exception as e:
        print(f"Piped API failed: {e}")

    # 2. თუ Piped-მა უარი თქვა, გადავდივართ მყარ ალტერნატიულ დამუშავებაზე (Cobalt/Wuk API-ების გაფართოებული სია)
    gateways = [
        "https://co.wuk.sh/api/json",
        "https://api.cobalt.tools/",
        "https://cobalt.moe/api/json"
    ]
    
    payload = {
        "url": f"https://www.youtube.com/watch?v={yt_id}",
        "videoQuality": "720",
        "downloadMode": "audio" if file_type == "mp3" else "regular"
    }
    
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }

    for api_url in gateways:
        try:
            res = requests.post(api_url, json=payload, headers=headers, timeout=12).json()
            file_url = res.get("url")
            if file_url:
                r = requests.get(file_url, timeout=60)
                if r.status_code == 200:
                    with open(local_filename, 'wb') as f: f.write(r.content)
                    return True
        except:
            continue
            
    return False

def background_download(url, file_type, task_id):
    try:
        ext = "mp3" if file_type == 'mp3' else "mp4"
        local_filename = os.path.join(TEMP_DIR, f"{task_id}.{ext}")
        
        # 1. TikTok ჩამოტვირთვა
        if "tiktok.com" in url:
            title = download_tiktok_fallback(url, local_filename)
            if title:
                download_tasks[task_id]['status'] = 'completed'
                download_tasks[task_id]['filename'] = local_filename
                download_tasks[task_id]['title'] = title
                return
            else:
                raise Exception("TikTok სერვერი დროებით გადატვირთულია.")

        # 2. YouTube ჩამოტვირთვა
        yt_id = get_clean_youtube_id(url)
        
        # ვცდილობთ ჩვეულებრივად (ლოკალურად)
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
                download_tasks[task_id]['title'] = info.get('title', 'Media_File')
                return
        except Exception:
            # თუ სტანდარტულმა გზამ არ იმუშავა, გადადის გაძლიერებულ ალტერნატიულ ქსელზე
            if yt_id:
                success = download_youtube_ultimate_fallback(yt_id, file_type, local_filename)
                if success:
                    download_tasks[task_id]['status'] = 'completed'
                    download_tasks[task_id]['filename'] = local_filename
                    download_tasks[task_id]['title'] = f"YouTube_{yt_id}"
                    return
            raise Exception("ყველა საჯარო სერვერი გადატვირთულია. გთხოვთ, სცადოთ 1 წუთში ხელახლა.")

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
    if "tiktok.com" in url: return jsonify({"title": "TikTok ვიდეო"})
    yt_id = get_clean_youtube_id(url)
    if yt_id: return jsonify({"title": f"YouTube ვიდეო ({yt_id})"})
    return jsonify({"title": "მედია ფაილი"})

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
