from flask import Blueprint, request, jsonify, send_file, after_this_request
import os
import subprocess
import shutil
import uuid
import urllib.parse
import logging
import yt_dlp
import re

tiktok_routes = Blueprint('tiktok', __name__)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Directory for temporary storage
DOWNLOAD_DIR = "downloads"
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

def sanitize_header(value):
    """Sanitize header value to remove invalid characters."""
    if not value:
        return "Unknown Title"
    sanitized = re.sub(r'[^\x20-\x7E]', '', value)
    sanitized = re.sub(r'\s+', ' ', sanitized).strip()
    return sanitized or "Unknown Title"

def extract_tiktok_info(url):
    """Extract video info and thumbnail using yt-dlp."""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'skip_download': True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            thumbnail = info.get('thumbnail', '')
            title = info.get('title', 'Unknown Title')
            return thumbnail, sanitize_header(title)
    except Exception as e:
        logger.error(f"Failed to extract info: {str(e)}")
        return '', 'Unknown Title'

@tiktok_routes.route("/api/tiktokurl", methods=["GET", "HEAD"])
def download_tiktok_video():
    raw_url = request.args.get("url")
    if not raw_url:
        logger.error("No URL provided")
        return jsonify({"error": "No URL provided, dumbass"}), 400

    try:
        decoded_url = urllib.parse.unquote(raw_url)
        logger.info(f"Raw URL: {raw_url}")
        logger.info(f"Decoded URL: {decoded_url}")

        if decoded_url.startswith("/api/tiktokurl?url=") or decoded_url.startswith("/api/tiktoaudio?url="):
            parsed = urllib.parse.parse_qs(urllib.parse.urlparse(decoded_url).query)
            tiktok_url = parsed.get("url", [None])[0]
        else:
            tiktok_url = decoded_url

        if not tiktok_url:
            logger.error("No valid URL extracted")
            return jsonify({"error": "Invalid URL, fix your shit"}), 400

        if not (tiktok_url.startswith("https://www.tiktok.com/") or tiktok_url.startswith("https://vm.tiktok.com/")):
            logger.error(f"Invalid TikTok URL: {tiktok_url}")
            return jsonify({"error": "URL must be from tiktok.com or vm.tiktok.com, asshole"}), 400

        logger.info(f"Processing TikTok URL: {tiktok_url}")

        thumbnail, title = extract_tiktok_info(tiktok_url)

        if request.method == "HEAD":
            response = jsonify({"status": "ok"})
            response.headers['x-tiktok-thumbnail'] = thumbnail or 'https://i.ibb.co/rRS0Y9rP/d0fa360c97e1c383.jpg'
            response.headers['x-tiktok-title'] = title
            return response

        filename = f"{uuid.uuid4()}.mp4"
        output_path = os.path.join(DOWNLOAD_DIR, filename)

        cmd = [
            "yt-dlp",
            "--retries", "3",
            "-f", "bestvideo+bestaudio/best",
            "--merge-output-format", "mp4",
            "-o", output_path,
            tiktok_url
        ]
        logger.info(f"Running command: {' '.join(cmd)}")
        result = subprocess.run(cmd, check=True, stderr=subprocess.PIPE, text=True)

        if not os.path.exists(output_path):
            logger.error("Download failed, no file found")
            return jsonify({"error": "Download failed, shit happens"}), 500

        response = send_file(
            output_path,
            as_attachment=True,
            download_name=f"{title}.mp4",
            mimetype='video/mp4'
        )
        response.headers['x-tiktok-thumbnail'] = thumbnail or 'https://i.ibb.co/rRS0Y9rP/d0fa360c97e1c383.jpg'
        response.headers['x-tiktok-title'] = title

        @after_this_request
        def cleanup(response):
            try:
                shutil.rmtree(DOWNLOAD_DIR)
                os.makedirs(DOWNLOAD_DIR)
                logger.info("Cleaned up downloads directory")
            except Exception as e:
                logger.error(f"Cleanup failed: {str(e)}")
            return response

        return response

    except subprocess.CalledProcessError as e:
        logger.error(f"yt-dlp error: {e.stderr}")
        return jsonify({"error": f"yt-dlp fucked up: {e.stderr}"}), 500
    except Exception as e:
        logger.error(f"General error: {str(e)}")
        return jsonify({"error": f"Shit went wrong: {str(e)}"}), 500

@tiktok_routes.route("/api/tiktoaudio", methods=["GET", "HEAD"])
def download_tiktok_audio():
    raw_url = request.args.get("url")
    if not raw_url:
        logger.error("No URL provided")
        return jsonify({"error": "No URL provided, dumbass"}), 400

    try:
        decoded_url = urllib.parse.unquote(raw_url)
        logger.info(f"Raw URL: {raw_url}")
        logger.info(f"Decoded URL: {decoded_url}")

        if decoded_url.startswith("/api/tiktokurl?url=") or decoded_url.startswith("/api/tiktoaudio?url="):
            parsed = urllib.parse.parse_qs(urllib.parse.urlparse(decoded_url).query)
            tiktok_url = parsed.get("url", [None])[0]
        else:
            tiktok_url = decoded_url

        if not tiktok_url:
            logger.error("No valid URL extracted")
            return jsonify({"error": "Invalid URL, fix your shit"}), 400

        if not (tiktok_url.startswith("https://www.tiktok.com/") or tiktok_url.startswith("https://vm.tiktok.com/")):
            logger.error(f"Invalid TikTok URL: {tiktok_url}")
            return jsonify({"error": "URL must be from tiktok.com or vm.tiktok.com, asshole"}), 400

        logger.info(f"Processing TikTok URL: {tiktok_url}")

        thumbnail, title = extract_tiktok_info(tiktok_url)

        if request.method == "HEAD":
            response = jsonify({"status": "ok"})
            response.headers['x-tiktok-thumbnail'] = thumbnail or 'https://i.ibb.co/rRS0Y9rP/d0fa360c97e1c383.jpg'
            response.headers['x-tiktok-title'] = title
            return response

        filename = f"{uuid.uuid4()}.mp3"
        output_path = os.path.join(DOWNLOAD_DIR, filename)

        cmd = [
            "yt-dlp",
            "--retries", "3",
            "-f", "bestaudio/best",
            "--extract-audio",
            "--audio-format", "mp3",
            "-o", output_path,
            tiktok_url
        ]
        logger.info(f"Running command: {' '.join(cmd)}")
        result = subprocess.run(cmd, check=True, stderr=subprocess.PIPE, text=True)

        if not os.path.exists(output_path):
            logger.error("Download failed, no file found")
            return jsonify({"error": "Download failed, shit happens"}), 500

        response = send_file(
            output_path,
            as_attachment=True,
            download_name=f"{title}.mp3",
            mimetype='audio/mpeg'
        )
        response.headers['x-tiktok-thumbnail'] = thumbnail or 'https://i.ibb.co/rRS0Y9rP/d0fa360c97e1c383.jpg'
        response.headers['x-tiktok-title'] = title

        @after_this_request
        def cleanup(response):
            try:
                shutil.rmtree(DOWNLOAD_DIR)
                os.makedirs(DOWNLOAD_DIR)
                logger.info("Cleaned up downloads directory")
            except Exception as e:
                logger.error(f"Cleanup failed: {str(e)}")
            return response

        return response

    except subprocess.CalledProcessError as e:
        logger.error(f"yt-dlp error: {e.stderr}")
        return jsonify({"error": f"yt-dlp fucked up: {e.stderr}"}), 500
    except Exception as e:
        logger.error(f"General error: {str(e)}")
        return jsonify({"error": f"Shit went wrong: {str(e)}"}), 500
