from flask import Blueprint, request, jsonify, send_file, after_this_request
import subprocess
import re
import json
import logging
from pathlib import Path
import time
import flask_limiter
from flask_limiter.util import get_remote_address
youtube_routes = Blueprint('youtube', __name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
limiter = flask_limiter.Limiter(
    key_func=get_remote_address,
    default_limits=["500 per 15min"]
)
def init_limiter(app):
    limiter.init_app(app)
def is_valid_youtube_url(url):
    return bool(re.match(r'^https?:\/\/(www\.)?(youtube\.com|youtu\.be)\/(watch\?v=|shorts\/|embed\/)?[A-Za-z0-9_-]{11}(\?.*)?$', url))
@youtube_routes.route('/download/audio', methods=['GET'])
@limiter.limit("500 per 15min")
def download_audio():
    song_url = request.args.get('song')
    quality = request.args.get('quality')
    cache_buster = request.args.get('cb', str(int(time.time())))
    if not song_url or not is_valid_youtube_url(song_url):
        return jsonify({'error': 'Please provide a valid YouTube URL.'}), 400
    valid_audio_qualities = ['128K', '192K', '320K']
    audio_quality = quality if quality in valid_audio_qualities else '192K'
    output_file = None
    try:
        cookies = Path('cookies.txt')
        if not cookies.exists():
            return jsonify({'error': 'Cookies file missing'}), 500
        meta_cmd = f'yt-dlp --dump-json --cookies "{cookies}" --js-runtimes node "{song_url}"'
        meta = subprocess.run(meta_cmd, shell=True, capture_output=True, text=True)
        if meta.returncode != 0 or not meta.stdout.strip():
            return jsonify({'error': 'Metadata extraction failed', 'details': meta.stderr}), 500
        logger.info(meta.stdout)
        logger.info(meta.stderr)
        info = json.loads(meta.stdout)
        title = re.sub(r'[^a-zA-Z0-9]', '_', info['title'])
        temp = Path('temp')
        temp.mkdir(exist_ok=True)
        output_file = temp / f"{title}_{audio_quality}_{cache_buster}.mp3"
        fmt = "bestaudio/best"
        cmd = (
            f'yt-dlp -x '
            f'--no-warnings --ignore-errors '
            f'-f "{fmt}" '
            f'--audio-format mp3 '
            f'--audio-quality {audio_quality} '
            f'--cookies "{cookies}" '
            f'--js-runtimes node '
            f'-o "{output_file}" "{song_url}"'
        )
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        logger.info(proc.stdout)
        logger.info(proc.stderr)
        if proc.returncode != 0:
            return jsonify({'error': 'yt-dlp audio failed', 'details': proc.stderr, 'stdout': proc.stdout}), 500
        if not output_file.exists():
            return jsonify({'error': 'Audio file missing', 'details': proc.stderr}), 500
        response = send_file(
            str(output_file),
            as_attachment=True,
            download_name=f"{title}_{audio_quality}.mp3",
            mimetype='audio/mpeg'
        )
        @after_this_request
        def cleanup(resp):
            if output_file.exists():
                output_file.unlink()
            return resp
        return response
    except Exception as e:
        if output_file and output_file.exists():
            output_file.unlink()
        return jsonify({'error': 'Audio download exception', 'details': str(e)}), 500
@youtube_routes.route('/download/video', methods=['GET'])
@limiter.limit("500 per 15min")
def download_video():
    song_url = request.args.get('song')
    quality = request.args.get('quality')
    cache_buster = request.args.get('cb', str(int(time.time())))
    if not song_url or not is_valid_youtube_url(song_url):
        return jsonify({'error': 'Please provide a valid YouTube URL.'}), 400
    valid_q = ['144p', '240p', '360p', '480p', '720p', '1080p']
    video_quality = quality if quality in valid_q else '1080p'
    output_file = None
    try:
        cookies = Path('cookies.txt')
        if not cookies.exists():
            return jsonify({'error': 'Cookies file missing'}), 500
        meta_cmd = f'yt-dlp --dump-json --cookies "{cookies}" --js-runtimes node "{song_url}"'
        meta = subprocess.run(meta_cmd, shell=True, capture_output=True, text=True)
        if meta.returncode != 0 or not meta.stdout.strip():
            return jsonify({'error': 'Metadata extraction failed', 'details': meta.stderr}), 500
        info = json.loads(meta.stdout)
        title = re.sub(r'[^a-zA-Z0-9]', '_', info['title'])
        temp = Path('temp')
        temp.mkdir(exist_ok=True)
        output_file = temp / f"{title}_{video_quality}_{cache_buster}.mp4"
        height = re.sub("[^0-9]", "", video_quality)
        fmt = f"bv*[height<={height}]+ba/b"
        cmd = (
            f'yt-dlp -f "{fmt}" '
            f'--merge-output-format mp4 '
            f'--cookies "{cookies}" '
            f'--js-runtimes node '
            f'-o "{output_file}" "{song_url}"'
        )
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if not output_file.exists():
            fb_fmt = "bv*+ba/b"
            fb = (
                f'yt-dlp -f "{fb_fmt}" '
                f'--merge-output-format mp4 '
                f'--cookies "{cookies}" '
                f'--js-runtimes node '
                f'-o "{output_file}" "{song_url}"'
            )
            subprocess.run(fb, shell=True, capture_output=True, text=True)
        if not output_file.exists():
            return jsonify({'error': 'Failed to download video'}), 500
        response = send_file(
            str(output_file),
            as_attachment=True,
            download_name=f"{title}_{video_quality}.mp4",
            mimetype='video/mp4'
        )
        @after_this_request
        def cleanup(resp):
            if output_file.exists():
                output_file.unlink()
            return resp
        return response
    except Exception as e:
        if output_file and output_file.exists():
            output_file.unlink()
        return jsonify({'error': 'Video download exception', 'details': str(e)}), 500
