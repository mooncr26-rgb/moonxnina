import os
import threading
import uuid
import requests
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
import yt_dlp

app = Flask(__name__, static_folder='.', static_url_path='')
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

def download_youtube_proxy_fallback(yt_id, file_type, local_filename):
    """ 
    YouTube ბლოკის ავლით ჩამოტვირთვა უახლესი, დაუბლოკავი საჯარო პროქსი-სერვერების ქსელით
    """
    instances = [
        "https://pipedapi.kavin.rocks/streams/",
        "https://pipedapi.colby.moe/streams/",
        "https://api.piped.yt/streams/",
        "https://pipedapi.us.to/streams/"
    ]
    
    for base_url in instances:
        try:
            res = requests.get(f"{base_url}{yt_id}", timeout=10).json()
            
            if file_type == "mp3" and "audioStreams" in res:
                audio_url = res["audioStreams"][0]["url"]
                r = requests.get(audio_url, timeout=45)
                if r.status_code == 200:
                    with open(local_filename, 'wb') as f: f.write(r.content)
                    return True
                    
            elif file_type == "mp4" and "videoStreams" in res:
                # ვეძებთ ვიდეოს, რომელსაც ხმაც მოჰყვება (videoOnly: False)
                streams = [s for s in res["videoStreams"] if not s.get("videoOnly")]
                if not streams: streams = res["videoStreams"]
                if streams:
                    video_url = streams[0]["url"]
                    r = requests.get(video_url, timeout=60)
                    if r.status_code == 200:
                        with open(local_filename, 'wb') as f: f.write(r.content)
                        return True
        except:
            continue
            
    # მესამე ალტერნატივა: პირდაპირი საჯარო კონვერტორები
    gateways = ["https://co.wuk.sh/api/json", "https://api.cobalt.tools/"]
    payload = {
        "url": f"https://www.youtube.com/watch?v={yt_id}",
        "videoQuality": "720",
        "downloadMode": "audio" if file_type == "mp3" else "regular"
    }
    for api_url in gateways:
        try:
            r_cobalt = requests.post(api_url, json=payload, headers={"Accept": "application/json", "Content-Type": "application/json"}, timeout=10).json()
            if "url" in r_cobalt:
                file_bytes = requests.get(r_cobalt["url"], timeout=60).content
                with open(local_filename, 'wb') as f: f.write(file_bytes)
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
                raise Exception("TikTok სერვერი დროებით მიუწვდომელია.")

        # 2. YouTube ჩამოტვირთვა
        yt_id = get_clean_youtube_id(url)
        ffmpeg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ffmpeg')
        cookies_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'www.youtube.com_cookies.txt')
        if not os.path.exists(cookies_path):
            cookies_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cookies.txt')
        
        opts = {
            'quiet': True,
            'nocheckcertificate': True,
            'outtmpl': os.path.join(TEMP_DIR, f"{task_id}.%(ext)s"),
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
            }
        }

        if os.path.exists(cookies_path):
            opts['cookiefile'] = cookies_path
        if os.path.exists(os.path.join(ffmpeg_path, 'ffmpeg')):
            opts['ffmpeg_location'] = os.path.join(ffmpeg_path, 'ffmpeg')

        if file_type == 'mp3':
            opts['format'] = 'bestaudio/best'
            opts['postprocessors'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'}]
        else:
            opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
            opts['merge_output_format'] = 'mp4'

        try:
            # ვცდილობთ ჩვეულებრივად (ლოკალურად)
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                
                if file_type == 'mp3' and not filename.endswith('.mp3'):
                    filename = filename.rsplit('.', 1)[0] + '.mp3'
                elif file_type == 'mp4' and not filename.endswith('.mp4'):
                    base_name = filename.rsplit('.', 1)[0]
                    if os.path.exists(base_name + '.mp4'): filename = base_name + '.mp4'
                
                if os.path.exists(filename):
                    download_tasks[task_id]['status'] = 'completed'
                    download_tasks[task_id]['filename'] = filename
                    download_tasks[task_id]['title'] = info.get('title', 'Media_File')
                    return
                else:
                    raise Exception()
        except:
            # 👑 თუ ლოკალურმა გზამ/ქუქიებმა უარი თქვა ბლოკის გამო, გადავდივართ მულტი-პროქსი ქსელზე
            if yt_id:
                success = download_youtube_proxy_fallback(yt_id, file_type, local_filename)
                if success:
                    download_tasks[task_id]['status'] = 'completed'
                    download_tasks[task_id]['filename'] = local_filename
                    download_tasks[task_id]['title'] = f"YouTube_{yt_id}"
                    return
            raise Exception("ჩამოტვირთვა ვერ მოხერხდა. სცადეთ სხვა ვიდეოს ლინკი.")

    except Exception as e:
        download_tasks[task_id]['status'] = 'failed'
        download_tasks[task_id]['error'] = str(e)

@app.route('/')
def index():
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), 'index.html')

@app.route('/api/analyze', methods=['POST'])
def analyze_video():
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
    return send_file(task['filename'], as_attachment=True, download_name=f"{safe_title or 'media'}.{ext}")

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
