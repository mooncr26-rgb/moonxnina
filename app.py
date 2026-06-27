import os
import threading
import uuid
import traceback
import requests
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads_temp")
os.makedirs(TEMP_DIR, exist_ok=True)

download_tasks = {}
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'

def get_clean_youtube_id(url):
    if "youtu.be/" in url:
        return url.split("youtu.be/")[-1].split("?")[0]
    if "v=" in url:
        return url.split("v=")[-1].split("&")[0]
    return None

# ---------------------------------------------------------------------------
# 👑 ახალი TikTok და YouTube API (Cobalt-ის სტაბილური მულტი-სერვერები)
# ---------------------------------------------------------------------------
COBALT_SERVERS = [
    "https://api.cobalt.tools/api/json",
    "https://cobalt.api.v01.io/api/json",
    "https://api.converts.cc/api/json"
]

def fetch_media_via_cobalt(url, mode="regular", quality="720"):
    payload = {
        "url": url,
        "videoQuality": quality,
        "downloadMode": mode, # 'regular' ვიდეოსთვის, 'audio' მუსიკისთვის
        "audioFormat": "mp3"
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT
    }
    
    for api_url in COBALT_SERVERS:
        try:
            r = requests.post(api_url, json=payload, headers=headers, timeout=12)
            if r.status_code == 200:
                res_data = r.json()
                if "url" in res_data or res_data.get("status") == "redirect":
                    return res_data
        except:
            continue
    return None

# ---------------------------------------------------------------------------
# Format Listing — /api/formats
# ---------------------------------------------------------------------------
@app.route('/api/formats', methods=['POST'])
def get_formats():
    data = request.json or {}
    url = data.get('url', '').strip()
    if not url:
        return jsonify({"error": "ბმული არ მოწოდებულა"}), 400

    # უნივერსალური იერიში - ჯერ ვტესტავთ Cobalt-ს, რომელიც უვლის გვერდს ბლოკებს
    cobalt_res = fetch_media_via_cobalt(url, mode="regular", quality="720")
    
    if cobalt_res and ("url" in cobalt_res or "picker" in cobalt_res):
        title = cobalt_res.get("text", "MOONNINA DOWNLOADER მედია")
        
        # თუ პირდაპირ სერვერმა დააბრუნა უნივერსალური ფაილი
        video_formats = [{
            "format_id": "cobalt_direct_video",
            "quality": "720p (HD)" if "tiktok" in url else "სტანდარტული MP4",
            "ext": "mp4",
            "filesize": None,
            "has_audio": True,
            "protocol": "direct"
        }]
        
        audio_formats = [{
            "format_id": "cobalt_direct_audio",
            "quality": "320kbps",
            "ext": "mp3",
            "filesize": None
        }]
        
        return jsonify({
            "title": title,
            "video": video_formats,
            "audio": audio_formats
        })

    # Fallback სპეციალურად YouTube-ისთვის Invidious API-ზე
    yt_id = get_clean_youtube_id(url)
    if yt_id:
        invidious_instances = ["https://invidious.io.lol/api/v1/videos/", "https://iv.melmac.space/api/v1/videos/"]
        for inv_url in invidious_instances:
            try:
                res = requests.get(f"{inv_url}{yt_id}", timeout=8).json()
                title = res.get("title", "MOONNINA - YouTube")
                
                video_formats = []
                audio_formats = []
                
                for fmt in res.get("formatStreams", []):
                    video_formats.append({
                        "format_id": f"invurl:{fmt['url']}",
                        "quality": fmt.get("qualityLabel", "720p"),
                        "ext": "mp4",
                        "filesize": None,
                        "has_audio": True
                    })
                
                audio_formats.append({
                    "format_id": "cobalt_direct_audio",
                    "quality": "საუკეთესო MP3",
                    "ext": "mp3",
                    "filesize": None
                })
                
                if video_formats:
                    return jsonify({"title": title, "video": video_formats[:4], "audio": audio_formats})
            except:
                continue

    return jsonify({
        "error": "სერვერების IP დაბლოკილია! გთხოვთ სცადოთ სხვა ვიდეოს ლინკი ან რამდენიმე წამში თავიდან."
    }), 502

# ---------------------------------------------------------------------------
# Background Download
# ---------------------------------------------------------------------------
def background_download(url, file_type, task_id, format_id=None):
    try:
        ext = "mp3" if file_type == 'mp3' else "mp4"
        local_filename = os.path.join(TEMP_DIR, f"{task_id}.{ext}")

        # თუ ფრონტენდმა პირდაპირი Invidious ნაკადი გადმოგვცა
        if format_id and format_id.startswith("invurl:"):
            stream_url = format_id[len("invurl:"):]
            r = requests.get(stream_url, timeout=90, stream=True)
            if r.status_code == 200:
                with open(local_filename, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192): f.write(chunk)
                download_tasks[task_id]['status'] = 'completed'
                download_tasks[task_id]['filename'] = local_filename
                download_tasks[task_id]['title'] = "MOONNINA_Media"
                return

        # სხვა შემთხვევაში ვიყენებთ მოწინავე Cobalt გზას
        mode = "audio" if file_type == "mp3" else "regular"
        res = fetch_media_via_cobalt(url, mode=mode, quality="1080" if file_type == "mp4" else "720")
        
        if res and "url" in res:
            file_url = res["url"]
            r = requests.get(file_url, timeout=120, stream=True)
            if r.status_code == 200:
                with open(local_filename, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192): f.write(chunk)
                download_tasks[task_id]['status'] = 'completed'
                download_tasks[task_id]['filename'] = local_filename
                download_tasks[task_id]['title'] = res.get("text", "MOONNINA_Downloaded")
                return

        raise Exception("ყველა გარე სერვერმა უარი თქვა ფაილის დამუშავებაზე.")

    except Exception as e:
        download_tasks[task_id]['status'] = 'failed'
        download_tasks[task_id]['error'] = str(e)

# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------
@app.route('/')
def index():
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), 'index.html')

@app.route('/api/analyze', methods=['POST'])
def analyze_video():
    return jsonify({"title": "MOONNINA DOWNLOADER"})

@app.route('/api/download', methods=['POST'])
def start_download():
    data = request.json or {}
    url = data.get('url')
    file_type = data.get('type')
    format_id = data.get('format_id')

    if not url or not file_type:
        return jsonify({"error": "url და type სავალდებულოა"}), 400

    task_id = str(uuid.uuid4())
    download_tasks[task_id] = {'status': 'processing', 'filename': ''}

    thread = threading.Thread(target=background_download, args=(url, file_type, task_id, format_id))
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
    safe_title = "".join([c for c in task['title'] if c.isalpha() or c.isdigit() or c == ' ']).rstrip()
    ext = task['filename'].split('.')[-1]
    return send_file(task['filename'], as_attachment=True, download_name=f"{safe_title or 'moonnina_media'}.{ext}")

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
