from flask import Blueprint, request, jsonify, send_file, after_this_request
import subprocess
import os
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

    if not song_url or not isinstance(song_url, str) or not is_valid_youtube_url(song_url):
        return jsonify({'error': 'Please provide a valid YouTube URL.'}), 400

    valid_audio_qualities = ['128K', '192K', '320K']
    audio_quality = quality if quality in valid_audio_qualities else '192K'

    output_file = None
    try:
        cookies_file = Path('cookies.txt')
        if not cookies_file.exists():
            return jsonify({'error': 'Cookies file missing, can’t authenticate with YouTube.'}), 500

        metadata_command = f'yt-dlp --dump-json --cookies "{cookies_file}" "{song_url}"'
        meta = subprocess.run(metadata_command, shell=True, capture_output=True, text=True)

        if meta.returncode != 0 or not meta.stdout.strip():
            return jsonify({'error': 'Metadata extraction failed', 'details': meta.stderr.strip()}), 500

        logger.info(meta.stdout)
        logger.info(meta.stderr)

        video_info = json.loads(meta.stdout)
        video_title = re.sub(r'[^a-zA-Z0-9]', '_', video_info['title'])

        temp_dir = Path('temp')
        temp_dir.mkdir(exist_ok=True)
        output_file = temp_dir / f"{video_title}_{audio_quality}_{cache_buster}.mp3"

        format_expr = "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio"

        yt_dlp_command = (
            f'yt-dlp -x --no-warnings --ignore-errors '
            f'-f "{format_expr}" '
            f'--audio-format mp3 --audio-quality {audio_quality} '
            f'--cookies "{cookies_file}" -o "{output_file}" "{song_url}"'
        )

        process = subprocess.run(yt_dlp_command, shell=True, capture_output=True, text=True)

        logger.info(process.stdout)
        logger.info(process.stderr)

        if process.returncode != 0:
            return jsonify({
                'error': 'yt-dlp audio failed',
                'details': process.stderr.strip(),
                'stdout': process.stdout.strip()
            }), 500

        if not output_file.exists():
            return jsonify({
                'error': 'Failed to download the audio (file missing)',
                'details': process.stderr.strip(),
                'stdout': process.stdout.strip()
            }), 500

        response = send_file(
            str(output_file),
            as_attachment=True,
            download_name=f"{video_title}_{audio_quality}.mp3",
            mimetype='audio/mpeg'
        )

        @after_this_request
        def cleanup(response):
            if output_file.exists():
                output_file.unlink()
            return response

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

    if not song_url or not isinstance(song_url, str) or not is_valid_youtube_url(song_url):
        return jsonify({'error': 'Please provide a valid YouTube URL.'}), 400

    valid_video_qualities = ['144p', '240p', '360p', '480p', '720p', '1080p']
    video_quality = quality if quality in valid_video_qualities else '1080p'

    output_file = None
    try:
        cookies_file = Path('cookies.txt')
        if not cookies_file.exists():
            return jsonify({'error': 'Cookies file missing, can’t authenticate with YouTube.'}), 500

        metadata_command = f'yt-dlp --dump-json --cookies "{cookies_file}" "{song_url}"'
        meta = subprocess.run(metadata_command, shell=True, capture_output=True, text=True)

        if meta.returncode != 0 or not meta.stdout.strip():
            return jsonify({'error': 'Metadata extraction failed', 'details': meta.stderr.strip()}), 500

        video_info = json.loads(meta.stdout)

        video_title = re.sub(r'[^a-zA-Z0-9]', '_', video_info['title'])

        temp_dir = Path('temp')
        temp_dir.mkdir(exist_ok=True)
        output_file = temp_dir / f"{video_title}_{video_quality}_{cache_buster}.mp4"

        height = re.sub("[^0-9]", "", video_quality)
        format_expr = f"bestvideo[height<={height}]+bestaudio/best"

        yt_dlp_command = (
            f'yt-dlp -f "{format_expr}" --merge-output-format mp4 '
            f'--cookies "{cookies_file}" -o "{output_file}" "{song_url}"'
        )

        proc = subprocess.run(yt_dlp_command, shell=True, capture_output=True, text=True)

        if not output_file.exists():
            fallback_expr = "bestvideo+bestaudio/best"
            fallback = (
                f'yt-dlp -f "{fallback_expr}" --merge-output-format mp4 '
                f'--cookies "{cookies_file}" -o "{output_file}" "{song_url}"'
            )
            subprocess.run(fallback, shell=True, capture_output=True, text=True)

        if not output_file.exists():
            return jsonify({'error': 'Failed to download the video.'}), 500

        response = send_file(
            str(output_file),
            as_attachment=True,
            download_name=f"{video_title}_{video_quality}.mp4",
            mimetype='video/mp4'
        )

        @after_this_request
        def cleanup(response):
            if output_file.exists():
                output_file.unlink()
            return response

        return response

    except Exception as e:
        if output_file and output_file.exists():
            output_file.unlink()
        return jsonify({'error': 'Failed to download the video.', 'details': str(e)}), 500
