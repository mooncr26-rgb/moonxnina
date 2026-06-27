import os
import threading
import uuid
import requests
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

# დროებითი საქაღალდე გადმოწერილი ფაილებისთვის
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
# 🌐 მულტი-სერვერული API მენეჯერი (ბლოკირებების ასავლელად)
# ---------------------------------------------------------------------------
COBALT_SERVERS = [
    "https://api.cobalt.tools/api/json",
    "https://cobalt.api.v01.io/api/json",
    "https://api.converts.cc/api/json"
]

def fetch_via_cobalt(url, mode="regular", quality="720"):
    payload = {
        "url": url,
        "videoQuality": quality,
        "downloadMode": mode,
        "audioFormat": "mp3"
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT
    }
    for api_url in COBALT_SERVERS:
        try:
            r = requests.post(api_url, json=payload, headers=headers, timeout=10)
            if r.status_code == 200:
                res_data = r.json()
                if "url" in res_data:
                    return {"url": res_data["url"], "title": res_data.get("text", "MOONNINA_Media")}
        except:
            continue
    return None

def fetch_tiktok_fallback(url):
    try:
        r = requests.post("https://www.tikwm.com/api/", data={'url': url}, timeout=10).json()
        if r.get('code') == 0:
            return {"url": r['data']['play'], "title": r['data'].get('title', 'MOONNINA_TikTok')}
    except:
        pass
    return None

# ---------------------------------------------------------------------------
# 🔍 1. ფორმატების ამოღება (GET FORMATS)
# ---------------------------------------------------------------------------
@app.route('/api/formats', methods=['POST'])
def get_formats():
    data = request.json or {}
    url = data.get('url', '').strip()
    if not url:
        return jsonify({"error": "ბმული არ მოწოდებულა"}), 400

    # ა) თუ არის TikTok
    if "tiktok.com" in url:
        res = fetch_via_cobalt(url, "regular") or fetch_tiktok_fallback(url)
        if res:
            return jsonify({
                "title": res["title"],
                "video": [{"format_id": f"direct:{res['url']}", "quality": "Original (No Watermark)", "ext": "mp4", "has_audio": True}],
                "audio": [{"format_id": f"direct:{res['url']}", "quality": "MP3 Audio", "ext": "mp3"}]
            })
        return jsonify({"error": "TikTok ვიდეო ვერ წაიკითხა. სცადეთ სხვა ლინკი."}), 502

    # ბ) თუ არის YouTube
    yt_id = get_clean_youtube_id(url)
    if yt_id:
        res = fetch_via_cobalt(url, "regular", "720")
        if res:
            return jsonify({
                "title": res["title"],
                "video": [
                    {"format_id": f"yt_res:{yt_id}:1080", "quality": "1080p (Full HD)", "ext": "mp4", "has_audio": True},
                    {"format_id": f"yt_res:{yt_id}:720", "quality": "720p (HD)", "ext": "mp4", "has_audio": True},
                    {"format_id": f"yt_res:{yt_id}:360", "quality": "360p", "ext": "mp4", "has_audio": True}
                ],
                "audio": [
                    {"format_id": f"yt_res:{yt_id}:audio", "quality": "320kbps MP3", "ext": "mp3"}
                ]
            })

    return jsonify({"error": "სერვერი გადატვირთულია ან ლინკი არასწორია. გთხოვთ სცადოთ თავიდან."}), 502

# ---------------------------------------------------------------------------
# ⏳ 2. ფონური ჩამოტვირთვა სერვერზე (BACKGROUND DOWNLOAD)
# ---------------------------------------------------------------------------
def background_download(url, file_type, task_id, format_id=None):
    try:
        ext = "mp3" if file_type == 'mp3' else "mp4"
        local_filename = os.path.join(TEMP_DIR, f"{task_id}.{ext}")
        final_url = None
        title = "moonnina_media"

        if format_id and format_id.startswith("direct:"):
            final_url = format_id[len("direct:"):]
            title = "MOONNINA_TikTok"
        elif format_id and format_id.startswith("yt_res:"):
            parts = format_id.split(":")
            yt_id = parts[1]
            mode = "audio" if file_type == "mp3" else "regular"
            qual = parts[2] if len(parts) > 2 and parts[2] != "audio" else "720"
            
            res = fetch_via_cobalt(f"https://www.youtube.com/watch?v={yt_id}", mode, qual)
            if res:
                final_url = res["url"]
                title = res["title"]

        # თუ წყარო მაინც ცარიელია, ბოლო ცდა პირდაპირი მოთხოვნით
        if not final_url:
            mode = "audio" if file_type == "mp3" else "regular"
            res = fetch_via_cobalt(url, mode, "720") or (fetch_tiktok_fallback(url) if "tiktok" in url else None)
            if res:
                final_url = res["url"]
                title = res["title"]

        if final_url:
            r = requests.get(final_url, timeout=180, stream=True, headers={"User-Agent": USER_AGENT})
            if r.status_code == 200:
                with open(local_filename, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=32768):
                        if chunk: f.write(chunk)
                
                download_tasks[task_id]['status'] = 'completed'
                download_tasks[task_id]['filename'] = local_filename
                download_tasks[task_id]['title'] = title
                return

        raise Exception("ვერცერთმა სერვერმა ვერ გამოიმუშავა ფაილის ლინკი.")

    except Exception as e:
        download_tasks[task_id]['status'] = 'failed'
        download_tasks[task_id]['error'] = str(e)

# ---------------------------------------------------------------------------
# 🚀 3. API ენდპოინტები
# ---------------------------------------------------------------------------
@app.route('/')
def index():
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), 'index.html')

@app.route('/api/download', methods=['POST'])
def start_download():
    data = request.json or {}
    url = data.get('url')
    file_type = data.get('type')
    format_id = data.get('format_id')

    if not url or not file_type:
        return jsonify({"error": "პარამეტრები არასრულია"}), 400

    task_id = str(uuid.uuid4())
    download_tasks[task_id] = {'status': 'processing', 'filename': ''}

    thread = threading.Thread(target=background_download, args=(url, file_type, task_id, format_id))
    thread.start()
    return jsonify({"task_id": task_id})

@app.route('/api/progress/<task_id>', methods=['GET'])
def get_progress(task_id):
    task = download_tasks.get(task_id)
    if not task: return jsonify({"error": "დავალება ვერ მოიძებნა"}), 404
    return jsonify(task)

@app.route('/api/get_file/<task_id>', methods=['GET'])
def get_file(task_id):
    task = download_tasks.get(task_id)
    if not task or task['status'] != 'completed': 
        return "ფაილი ჯერ არ არის მზად ჩამოსატვირთად.", 400
    
    # სახელიდან სიმბოლოების გასუფთავება
    safe_title = "".join([c for c in task['title'] if c.isalpha() or c.isdigit() or c == ' ']).strip()
    ext = task['filename'].split('.')[-1]
    
    return send_file(
        task['filename'], 
        as_attachment=True, 
        download_name=f"{safe_title or 'moonnina_download'}.{ext}"
    )

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
