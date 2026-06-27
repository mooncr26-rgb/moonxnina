import os
import threading
import uuid
import traceback
import requests
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
import yt_dlp

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads_temp")
os.makedirs(TEMP_DIR, exist_ok=True)

download_tasks = {}

USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')


def get_cookies_path():
    base = os.path.dirname(os.path.abspath(__file__))
    p1 = os.path.join(base, 'www.youtube.com_cookies.txt')
    p2 = os.path.join(base, 'cookies.txt')
    if os.path.exists(p1):
        return p1
    if os.path.exists(p2):
        return p2
    return None


def get_ffmpeg_path():
    base = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.join(base, 'ffmpeg', 'ffmpeg')
    if os.path.exists(candidate):
        return os.path.join(base, 'ffmpeg')
    return None


def get_clean_youtube_id(url):
    if "youtu.be/" in url:
        return url.split("youtu.be/")[-1].split("?")[0]
    if "v=" in url:
        return url.split("v=")[-1].split("&")[0]
    return None


PIPED_INSTANCES = [
    "https://pipedapi.kavin.rocks/streams/",
    "https://pipedapi.colby.moe/streams/",
    "https://api.piped.yt/streams/",
    "https://pipedapi.us.to/streams/"
]


def base_ydl_opts():
    opts = {
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'http_headers': {'User-Agent': USER_AGENT},
    }
    cookies_path = get_cookies_path()
    if cookies_path:
        opts['cookiefile'] = cookies_path
    ffmpeg_path = get_ffmpeg_path()
    if ffmpeg_path:
        opts['ffmpeg_location'] = ffmpeg_path
    
    proxy = os.environ.get('YTDLP_PROXY')
    if proxy:
        opts['proxy'] = proxy
    return opts


# ---------------------------------------------------------------------------
# TikTok fallback
# ---------------------------------------------------------------------------

def download_tiktok_fallback(url, local_filename):
    try:
        api_url = "https://www.tikwm.com/api/"
        headers = {'User-Agent': USER_AGENT}
        res = requests.post(api_url, data={'url': url}, headers=headers, timeout=20).json()
        if res.get('code') == 0:
            video_url = res['data']['play']
            video_bytes = requests.get(video_url, headers=headers, timeout=30).content
            with open(local_filename, 'wb') as f:
                f.write(video_bytes)
            return res['data'].get('title', 'MOONNINA_DOWNLOADER_TikTok')
        print(f"[TikTok] API returned code={res.get('code')} msg={res.get('msg')}")
    except Exception as e:
        print(f"[TikTok] Error: {e}")
    return None


def get_tiktok_info(url):
    try:
        headers = {'User-Agent': USER_AGENT}
        res = requests.post("https://www.tikwm.com/api/", data={'url': url}, headers=headers, timeout=20).json()
        if res.get('code') == 0:
            data = res['data']
            size = data.get('size') or data.get('hd_size')
            return {
                "title": data.get('title', 'MOONNINA DOWNLOADER - TikTok'),
                "video": [{
                    "format_id": "tiktok_direct",
                    "quality": "Original (no watermark)",
                    "ext": "mp4",
                    "filesize": size,
                    "has_audio": True,
                    "protocol": "direct",
                }],
                "audio": []
            }
    except Exception as e:
        print(f"[TikTok formats] Error: {e}")
    return None


# ---------------------------------------------------------------------------
# YouTube proxy fallback
# ---------------------------------------------------------------------------

def download_youtube_proxy_fallback(yt_id, file_type, local_filename):
    for base_url in PIPED_INSTANCES:
        try:
            res = requests.get(f"{base_url}{yt_id}", timeout=10).json()

            if file_type == "mp3" and "audioStreams" in res and res["audioStreams"]:
                audio_url = res["audioStreams"][0]["url"]
                r = requests.get(audio_url, timeout=45, headers={'User-Agent': USER_AGENT})
                if r.status_code == 200:
                    with open(local_filename, 'wb') as f:
                        f.write(r.content)
                    return True

            elif file_type == "mp4" and "videoStreams" in res and res["videoStreams"]:
                streams = [s for s in res["videoStreams"] if not s.get("videoOnly")]
                if not streams:
                    streams = res["videoStreams"]
                if streams:
                    video_url = streams[0]["url"]
                    r = requests.get(video_url, timeout=60, headers={'User-Agent': USER_AGENT})
                    if r.status_code == 200:
                        with open(local_filename, 'wb') as f:
                            f.write(r.content)
                        return True
        except Exception as e:
            print(f"[Piped:{base_url}] failed: {e}")
            continue

    gateways = ["https://api.cobalt.tools/api/json"]
    payload = {
        "url": f"https://www.youtube.com/watch?v={yt_id}",
        "videoQuality": "720",
        "downloadMode": "audio" if file_type == "mp3" else "regular"
    }
    for api_url in gateways:
        try:
            r_cobalt = requests.post(
                api_url, json=payload,
                headers={"Accept": "application/json", "Content-Type": "application/json", "User-Agent": USER_AGENT},
                timeout=15
            ).json()
            if "url" in r_cobalt:
                file_bytes = requests.get(r_cobalt["url"], headers={'User-Agent': USER_AGENT}, timeout=60).content
                with open(local_filename, 'wb') as f:
                    f.write(file_bytes)
                return True
            print(f"[Cobalt] no url in response: {r_cobalt}")
        except Exception as e:
            print(f"[Cobalt:{api_url}] failed: {e}")
            continue

    return False


def get_youtube_formats_via_piped(yt_id):
    for base_url in PIPED_INSTANCES:
        try:
            res = requests.get(f"{base_url}{yt_id}", timeout=10).json()
            title = res.get('title', 'MOONNINA DOWNLOADER - YouTube')

            video_list, audio_list, seen = [], [], set()

            for s in res.get('videoStreams', []):
                quality = s.get('quality')
                stream_url = s.get('url')
                if not quality or not stream_url:
                    continue
                if quality in seen:
                    continue
                seen.add(quality)
                video_list.append({
                    "format_id": f"pipedurl:{stream_url}",
                    "quality": quality,
                    "ext": (s.get('format') or 'mp4').lower(),
                    "filesize": None,
                    "has_audio": not s.get('videoOnly', False),
                    "protocol": "piped",
                })

            for s in res.get('audioStreams', []):
                stream_url = s.get('url')
                if not stream_url:
                    continue
                quality = s.get('quality') or 'Audio'
                audio_list.append({
                    "format_id": f"pipedurl:{stream_url}",
                    "quality": str(quality),
                    "ext": (s.get('format') or 'm4a').lower(),
                    "filesize": None,
                })

            if video_list or audio_list:
                return {"title": title, "video": video_list[:8], "audio": audio_list[:4]}
        except Exception as e:
            print(f"[Piped formats:{base_url}] failed: {e}")
            continue
    return None


# ---------------------------------------------------------------------------
# Format listing
# ---------------------------------------------------------------------------

@app.route('/api/formats', methods=['POST'])
def get_formats():
    data = request.json or {}
    url = data.get('url', '').strip()
    if not url:
        return jsonify({"error": "ბმული არ მოწოდებულა"}), 400

    if "tiktok.com" in url:
        info = get_tiktok_info(url)
        if info:
            return jsonify(info)
        return jsonify({"error": "TikTok ვიდეოს ინფორმაცია ვერ მოიძებნა. გთხოვთ სცადოთ ხელახლა."}), 502

    ydl_opts = base_ydl_opts()
    ydl_opts['skip_download'] = True

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        print(f"[formats] extract_info failed: {e}")
        traceback.print_exc()

        yt_id = get_clean_youtube_id(url)
        if yt_id:
            fallback = get_youtube_formats_via_piped(yt_id)
            if fallback:
                return jsonify(fallback)

        return jsonify({
            "error": "ვიდეოს ინფორმაციის წაკითხვა ვერ მოხერხდა. "
                     "შესაძლოა YouTube-მა დროებით დაბლოკა სერვერის IP, "
                     "ან ვიდეო არ არსებობს/პრივატულია."
        }), 502

    video_list = []
    audio_list = []
    seen = set()

    for f in info.get('formats', []):
        height = f.get('height')
        vcodec = f.get('vcodec', 'none')
        acodec = f.get('acodec', 'none')
        ext = f.get('ext')
        filesize = f.get('filesize') or f.get('filesize_approx')

        if vcodec and vcodec != 'none' and height:
            key = ('v', height, ext)
            if key in seen:
                continue
            seen.add(key)
            video_list.append({
                "format_id": f.get('format_id'),
                "quality": f"{height}p",
                "height": height,
                "ext": ext,
                "filesize": filesize,
                "has_audio": acodec not in (None, 'none'),
                "protocol": f.get('protocol', ''),
            })
        elif (not vcodec or vcodec == 'none') and acodec and acodec != 'none':
            abr = f.get('abr') or 0
            key = ('a', round(abr), ext)
            if key in seen:
                continue
            seen.add(key)
            audio_list.append({
                "format_id": f.get('format_id'),
                "quality": f"{int(abr)}kbps" if abr else "Audio",
                "ext": ext,
                "filesize": filesize,
            })

    video_list.sort(key=lambda x: x['height'] or 0, reverse=True)
    audio_list.sort(key=lambda x: x['filesize'] or 0, reverse=True)

    return jsonify({
        "title": info.get('title', 'MOONNINA DOWNLOADER მედია'),
        "video": video_list[:8],
        "audio": audio_list[:4],
    })


# ---------------------------------------------------------------------------
# Background download
# ---------------------------------------------------------------------------

def background_download(url, file_type, task_id, format_id=None, has_audio=True):
    try:
        ext = "mp3" if file_type == 'mp3' else "mp4"
        local_filename = os.path.join(TEMP_DIR, f"{task_id}.{ext}")

        # 1. TikTok
        if "tiktok.com" in url:
            title = download_tiktok_fallback(url, local_filename)
            if title:
                download_tasks[task_id]['status'] = 'completed'
                download_tasks[task_id]['filename'] = local_filename
                download_tasks[task_id]['title'] = title
                return
            else:
                raise Exception("TikTok სერვერი დროებით მიუწვდომელია.")

        # 2. Direct stream URL (Piped fallback)
        if format_id and format_id.startswith("pipedurl:"):
            stream_url = format_id[len("pipedurl:"):]
            try:
                r = requests.get(stream_url, timeout=90, headers={'User-Agent': USER_AGENT})
                if r.status_code == 200:
                    with open(local_filename, 'wb') as f:
                        f.write(r.content)
                    download_tasks[task_id]['status'] = 'completed'
                    download_tasks[task_id]['filename'] = local_filename
                    download_tasks[task_id]['title'] = f"MOONNINA_{get_clean_youtube_id(url) or task_id}"
                    return
                raise Exception(f"Piped stream returned status {r.status_code}")
            except Exception as e:
                print(f"[pipedurl] direct download failed: {e}")
                raise Exception("ამ ხარისხის ჩამოტვირთვა ვერ მოხერხდა, სცადეთ სხვა ხარისხი.")

        # 3. YouTube / Other sites
        yt_id = get_clean_youtube_id(url)
        opts = base_ydl_opts()
        opts['outtmpl'] = os.path.join(TEMP_DIR, f"{task_id}.%(ext)s")

        if file_type == 'mp3':
            opts['format'] = format_id if format_id else 'bestaudio/best'
            opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320'
            }]
        else:
            if format_id:
                opts['format'] = format_id if has_audio else f"{format_id}+bestaudio/best"
            else:
                opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
            opts['merge_output_format'] = 'mp4'

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)

                if file_type == 'mp3' and not filename.endswith('.mp3'):
                    filename = filename.rsplit('.', 1)[0] + '.mp3'
                elif file_type == 'mp4' and not filename.endswith('.mp4'):
                    base_name = filename.rsplit('.', 1)[0]
                    if os.path.exists(base_name + '.mp4'):
                        filename = base_name + '.mp4'

                if os.path.exists(filename):
                    download_tasks[task_id]['status'] = 'completed'
                    download_tasks[task_id]['filename'] = filename
                    download_tasks[task_id]['title'] = info.get('title', 'MOONNINA_File')
                    return
                else:
                    raise Exception("yt-dlp-მა დაასრულა შეცდომის გარეშე, მაგრამ ფაილი არ შეიქმნა.")
        except Exception as e:
            print(f"[yt-dlp] local download failed for task {task_id}: {e}")
            traceback.print_exc()

            if yt_id:
                success = download_youtube_proxy_fallback(yt_id, file_type, local_filename)
                if success:
                    download_tasks[task_id]['status'] = 'completed'
                    download_tasks[task_id]['filename'] = local_filename
                    download_tasks[task_id]['title'] = f"MOONNINA_{yt_id}"
                    return
            raise Exception(
                "ჩამოტვირთვა ვერ მოხერხდა (YouTube-მა შესაძლოა დაბლოკა სერვერის IP). "
                "სცადეთ სხვა ვიდეო ან ხარისხი."
            )

    except Exception as e:
        download_tasks[task_id]['status'] = 'failed'
        download_tasks[task_id]['error'] = str(e)


# ---------------------------------------------------------------------------
# Routes
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
    has_audio = data.get('has_audio', True)

    if not url or not file_type:
        return jsonify({"error": "url და type სავალდებულოა"}), 400

    task_id = str(uuid.uuid4())
    download_tasks[task_id] = {'progress': 50, 'status': 'processing', 'filename': ''}

    thread = threading.Thread(
        target=background_download,
        args=(url, file_type, task_id, format_id, has_audio)
    )
    thread.start()
    return jsonify({"task_id": task_id})


@app.route('/api/progress/<task_id>', methods=['GET'])
def get_progress(task_id):
    task = download_tasks.get(task_id)
    if not task:
        return jsonify({"error": "ვერ მოიძებნა"}), 404
    return jsonify(task)


@app.route('/api/get_file/<task_id>', methods=['GET'])
def get_file(task_id):
    task = download_tasks.get(task_id)
    if not task or task['status'] != 'completed':
        return "არ არის მზად", 400
    safe_title = "".join([c for c in task['title'] if c.isalpha() or c.isdigit() or c == ' ']).rstrip()
    ext = task['filename'].split('.')[-1]
    return send_file(task['filename'], as_attachment=True, download_name=f"{safe_title or 'moonnina_media'}.{ext}")


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
