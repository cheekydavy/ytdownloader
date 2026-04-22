from flask import Blueprint, request, jsonify, send_file, after_this_request, Response
import os
import uuid
import urllib.parse
import urllib.request
import logging
import re
import requests

tiktok_routes = Blueprint('tiktok', __name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DOWNLOAD_DIR = "downloads"
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

TIKWM_API = "https://www.tikwm.com/api/"
TIKWM_HEADERS = {
    "User-Agent": "ToxicAPIs/2.0",
    "Referer": "https://www.tikwm.com/"
}
FALLBACK_THUMB = "https://i.ibb.co/rRS0Y9rP/d0fa360c97e1c383.jpg"

VALID_TIKTOK_PREFIXES = (
    "https://www.tiktok.com/",
    "https://vt.tiktok.com",
    "https://vm.tiktok.com/",
    "http://www.tiktok.com/",
    "http://vt.tiktok.com",
    "http://vm.tiktok.com/",
)

SHORT_TIKTOK_HOSTS = ("vm.tiktok", "vt.tiktok", "m.tiktok")


def sanitize_header(value):
    if not value:
        return "Unknown Title"
    sanitized = re.sub(r'[^\x20-\x7E]', '', value)
    sanitized = re.sub(r'\s+', ' ', sanitized).strip()
    return sanitized or "Unknown Title"


def resolve_short_url(url):
    if not any(h in url for h in SHORT_TIKTOK_HOSTS):
        return url
    try:
        r = requests.get(
            url,
            allow_redirects=True,
            timeout=10,
            headers={"User-Agent": "TikTok 26.2.0 rv:262018 (iPhone; iOS 14.4.2; en_US) Cronet"}
        )
        resolved = r.url
        if resolved and "tiktok.com" in resolved:
            return resolved
    except Exception as e:
        logger.warning(f"Short URL resolution failed: {e}")
    return url


def fetch_tikwm(url):
    resolved = resolve_short_url(url)
    params = {"url": resolved, "hd": "1"}
    r = requests.get(TIKWM_API, params=params, headers=TIKWM_HEADERS, timeout=20)
    r.raise_for_status()
    j = r.json()
    if j.get("code") == 0 and j.get("data"):
        return j["data"]
    raise ValueError(j.get("msg") or "TikWM API returned no data")


def stream_remote_file(remote_url, filename, mimetype):
    local_path = os.path.join(DOWNLOAD_DIR, f"{uuid.uuid4()}_{filename}")
    urllib.request.urlretrieve(remote_url, local_path)

    @after_this_request
    def cleanup(response):
        try:
            if os.path.exists(local_path):
                os.remove(local_path)
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")
        return response

    return send_file(local_path, as_attachment=True, download_name=filename, mimetype=mimetype)


def validate_tiktok_url(raw_url):
    if not raw_url:
        return None, ("Missing required param: url", 400)
    decoded = urllib.parse.unquote(raw_url)
    if not any(decoded.startswith(p) for p in VALID_TIKTOK_PREFIXES):
        return None, ("URL must be a valid TikTok link.", 400)
    return decoded, None


@tiktok_routes.route("/api/tiktokurl", methods=["GET", "HEAD"])
def download_tiktok_video():
    tiktok_url, err = validate_tiktok_url(request.args.get("url"))
    if err:
        return jsonify({"error": err[0]}), err[1]

    try:
        data = fetch_tikwm(tiktok_url)
    except Exception as e:
        logger.error(f"TikWM fetch error: {e}")
        return jsonify({"error": f"Could not fetch TikTok video: {e}"}), 502

    title = sanitize_header(data.get("title"))
    thumbnail = data.get("cover") or FALLBACK_THUMB
    video_url = data.get("hdplay") or data.get("play")

    if request.method == "HEAD":
        resp = jsonify({"status": "ok"})
        resp.headers["x-tiktok-thumbnail"] = thumbnail
        resp.headers["x-tiktok-title"] = title
        return resp

    if not video_url:
        return jsonify({"error": "No video URL returned by TikWM"}), 502

    try:
        resp = stream_remote_file(video_url, f"{title}.mp4", "video/mp4")
        resp.headers["x-tiktok-thumbnail"] = thumbnail
        resp.headers["x-tiktok-title"] = title
        return resp
    except Exception as e:
        logger.error(f"Video stream error: {e}")
        return jsonify({"error": f"Failed to stream video: {e}"}), 500


@tiktok_routes.route("/api/tiktoaudio", methods=["GET", "HEAD"])
def download_tiktok_audio():
    tiktok_url, err = validate_tiktok_url(request.args.get("url"))
    if err:
        return jsonify({"error": err[0]}), err[1]

    try:
        data = fetch_tikwm(tiktok_url)
    except Exception as e:
        logger.error(f"TikWM fetch error: {e}")
        return jsonify({"error": f"Could not fetch TikTok audio: {e}"}), 502

    title = sanitize_header(data.get("title"))
    thumbnail = data.get("cover") or FALLBACK_THUMB
    music_url = data.get("music")

    if request.method == "HEAD":
        resp = jsonify({"status": "ok"})
        resp.headers["x-tiktok-thumbnail"] = thumbnail
        resp.headers["x-tiktok-title"] = title
        return resp

    if not music_url:
        return jsonify({"error": "No audio URL returned by TikWM"}), 502

    try:
        resp = stream_remote_file(music_url, f"{title}.mp3", "audio/mpeg")
        resp.headers["x-tiktok-thumbnail"] = thumbnail
        resp.headers["x-tiktok-title"] = title
        return resp
    except Exception as e:
        logger.error(f"Audio stream error: {e}")
        return jsonify({"error": f"Failed to stream audio: {e}"}), 500
