import os
import requests
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

def get_yt_id(url):
    if "youtu.be/" in url: return url.split("youtu.be/")[-1].split("?")[0]
    if "v=" in url: return url.split("v=")[-1].split("&")[0]
    return None

def fetch_youtube_streams(yt_id):
    # 1. Piped API Proxy - სრულიად არიდებს თავს IP ბლოკებს
    piped_instances = [
        "https://pipedapi.kavin.rocks",
        "https://api.piped.yt",
        "https://pipedapi.adminforge.de",
        "https://pipedapi.smnz.de",
        "https://pipedapi.us.to"
    ]
    
    for instance in piped_instances:
        try:
            r = requests.get(f"{instance}/streams/{yt_id}", timeout=8)
            if r.status_code == 200:
                data = r.json()
                mp4_url = None
                mp3_url = None
                
                # ვიღებთ MP4-ს ხმით (videoOnly: false)
                if data.get("videoStreams"):
                    for stream in data["videoStreams"]:
                        if stream.get("format") == "MPEG_4" and not stream.get("videoOnly"):
                            mp4_url = stream["url"]
                            break
                    if not mp4_url:  # თუ ხმიანი ვერ იპოვა, ვიღებთ ნებისმიერს
                        mp4_url = data["videoStreams"][0]["url"]
                        
                # ვიღებთ აუდიოს
                if data.get("audioStreams"):
                    mp3_url = data["audioStreams"][0]["url"]
                    
                if mp4_url or mp3_url:
                    return {
                        "title": data.get("title", "MOONNINA YouTube Video"),
                        "mp4": mp4_url,
                        "mp3": mp3_url
                    }
        except:
            continue
            
    # 2. Fallback: Cobalt API (გაყალბებული ჰედერებით, რათა ეგონოთ რომ თავიანთი საიტიდან შევდივართ)
    try:
        headers = {
            "Accept": "application/json", 
            "Content-Type": "application/json", 
            "Origin": "https://cobalt.tools", 
            "Referer": "https://cobalt.tools/", 
            "User-Agent": USER_AGENT
        }
        payload = {"url": f"https://www.youtube.com/watch?v={yt_id}", "videoQuality": "720"}
        r = requests.post("https://api.cobalt.tools/api/json", json=payload, headers=headers, timeout=8)
        
        if r.status_code == 200 and "url" in r.json():
            mp4_url = r.json()["url"]
            # აუდიოს მოთხოვნა
            payload["downloadMode"] = "audio"
            r_audio = requests.post("https://api.cobalt.tools/api/json", json=payload, headers=headers, timeout=8)
            mp3_url = r_audio.json()["url"] if r_audio.status_code == 200 else None
            
            return {"title": "MOONNINA YouTube Media", "mp4": mp4_url, "mp3": mp3_url}
    except:
        pass

    return None

def fetch_tiktok_streams(url):
    # 1. TikWM API
    try:
        r = requests.post("https://www.tikwm.com/api/", data={'url': url}, timeout=8).json()
        if r.get("code") == 0:
            return {
                "title": r['data'].get("title", "MOONNINA TikTok Video"),
                "mp4": r['data']['play'],
                "mp3": r['data'].get('music')
            }
    except: pass
    
    # 2. TiklyDown API
    try:
        r = requests.get(f"https://api.tiklydown.eu.org/api/download?url={url}", timeout=8).json()
        if "video" in r:
            return {
                "title": "MOONNINA TikTok Video",
                "mp4": r["video"].get("noWatermark"),
                "mp3": r.get("music", {}).get("play_url")
            }
    except: pass
    return None

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route('/')
def index():
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), 'index.html')

@app.route('/api/analyze', methods=['POST'])
def analyze():
    url = request.json.get('url', '').strip()
    if not url: return jsonify({"error": "გთხოვთ ჩასვათ ვალიდური ლინკი!"}), 400
    
    if "tiktok.com" in url:
        res = fetch_tiktok_streams(url)
        if res: return jsonify(res)
        return jsonify({"error": "TikTok ვიდეოს მონაცემები ვერ მოიძებნა. შესაძლოა პრივატულია."}), 502
        
    yt_id = get_yt_id(url)
    if yt_id:
        res = fetch_youtube_streams(yt_id)
        if res: return jsonify(res)
        return jsonify({"error": "მონაცემების ამოღება ვერ მოხერხდა. ვიდეო დაბლოკილია ან სერვერები გადატვირთულია."}), 502
        
    return jsonify({"error": "ფორმატი უცნობია. მხარდაჭერილია მხოლოდ YouTube და TikTok."}), 400

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
