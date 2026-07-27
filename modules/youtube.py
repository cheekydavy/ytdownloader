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

def sanitize_title(title):
    clean = re.sub(r'[\\/:*?"<>|]', '', title)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean or 'audio'

def safe_filename(title):
    return re.sub(r'[^a-zA-Z0-9 _-]', '_', title).strip() or 'audio'

JS_ARGS = '--js-runtimes node'


@youtube_routes.route('/download/audio', methods=['GET'])
@limiter.limit("500 per 15min")
def download_audio():
    song_url = request.args.get('song')
    quality = request.args.get('quality')
    cache_buster = request.args.get('cb', str(int(time.time())))
    if not song_url or not isinstance(song_url, str) or not is_valid_youtube_url(song_url):
        logger.error(f"[Audio] Invalid or missing YouTube URL: {song_url}")
        return jsonify({'error': 'Please provide a valid YouTube URL.'}), 400

    valid_audio_qualities = ['128K', '192K', '320K']
    audio_quality = quality if quality in valid_audio_qualities else '192K'
    output_file = None
    try:
        cookies_file = Path('cookies.txt')
        cookies_arg = f'--cookies "{cookies_file}"' if cookies_file.exists() else ''

        temp_dir = Path('temp')
        temp_dir.mkdir(exist_ok=True)

        metadata_command = f'yt-dlp --dump-json --no-playlist {JS_ARGS} {cookies_arg} "{song_url}"'
        logger.info(f"[Audio] Fetching metadata for URL: {song_url}, cacheBuster: {cache_buster}")
        result = subprocess.run(metadata_command, shell=True, capture_output=True, text=True)

        if result.returncode != 0 or not result.stdout.strip():
            logger.error(f"[Audio] Metadata failed: {result.stderr}")
            return jsonify({'error': 'Failed to fetch video metadata.', 'details': result.stderr}), 500

        video_info = json.loads(result.stdout)
        original_title = video_info.get('title', 'audio')
        safe_title = safe_filename(original_title)
        display_title = sanitize_title(original_title)
        logger.info(f"[Audio] Title: {original_title}, quality: {audio_quality}")

        output_file = temp_dir / f"{safe_title}_{cache_buster}.mp3"

        yt_dlp_command = (
            f'yt-dlp -x --audio-format mp3 --audio-quality {audio_quality} '
            f'--embed-thumbnail --convert-thumbnails jpg '
            f'--no-playlist {JS_ARGS} {cookies_arg} '
            f'-o "{output_file}" "{song_url}"'
        )
        logger.info(f"[Audio] Running yt-dlp")
        result = subprocess.run(yt_dlp_command, shell=True, capture_output=True, text=True)
        if result.stderr:
            logger.info(f"[Audio] yt-dlp stderr: {result.stderr}")

        if not output_file.exists():
            logger.error('[Audio] Output file not found after yt-dlp command.')
            return jsonify({'error': 'Failed to download the audio.', 'details': result.stderr}), 500

        download_name = f"{display_title}.mp3"
        response = send_file(
            str(output_file),
            as_attachment=True,
            download_name=download_name,
            mimetype='audio/mpeg'
        )

        @after_this_request
        def cleanup(response):
            for ext in ('', '.jpg', '.jpeg', '.png', '.webp'):
                p = Path(str(output_file).replace('.mp3', ext) if ext else str(output_file))
                if p.exists():
                    try:
                        p.unlink()
                    except Exception:
                        pass
            return response
        return response
    except Exception as e:
        logger.error(f"[Audio] Error in /download/audio: {str(e)}")
        if output_file and output_file.exists():
            output_file.unlink()
        return jsonify({'error': 'Failed to download the audio.', 'details': str(e)}), 500


@youtube_routes.route('/download/video', methods=['GET'])
@limiter.limit("500 per 15min")
def download_video():
    song_url = request.args.get('song')
    quality = request.args.get('quality')
    cache_buster = request.args.get('cb', str(int(time.time())))
    if not song_url or not isinstance(song_url, str) or not is_valid_youtube_url(song_url):
        logger.error(f"[Video] Invalid or missing YouTube URL: {song_url}")
        return jsonify({'error': 'Please provide a valid YouTube URL.'}), 400

    valid_video_qualities = ['144p', '240p', '360p', '480p', '720p', '1080p']
    video_quality = quality if quality in valid_video_qualities else '1080p'

    quality_format_map = {
        '144p': ['160+140', '160+251', 'bestvideo[height<=144]+bestaudio/best'],
        '240p': ['133+140', '133+251', 'bestvideo[height<=240]+bestaudio/best'],
        '360p': ['18', '134+140', '134+251', 'bestvideo[height<=360]+bestaudio/best'],
        '480p': ['135+140', '135+251', 'bestvideo[height<=480]+bestaudio/best'],
        '720p': ['22', '136+140', '136+251', 'bestvideo[height<=720]+bestaudio/best'],
        '1080p': ['137+140', '137+251', 'bestvideo[height<=1080]+bestaudio/best'],
    }
    format_codes = quality_format_map.get(video_quality, ['bestvideo+bestaudio/best'])

    output_file = None
    try:
        cookies_file = Path('cookies.txt')
        cookies_arg = f'--cookies "{cookies_file}"' if cookies_file.exists() else ''

        metadata_command = f'yt-dlp --dump-json --no-playlist {JS_ARGS} {cookies_arg} "{song_url}"'
        logger.info(f"[Video] Fetching metadata for URL: {song_url}, cacheBuster: {cache_buster}")
        result = subprocess.run(metadata_command, shell=True, capture_output=True, text=True)

        if result.returncode != 0 or not result.stdout.strip():
            logger.error(f"[Video] Metadata failed: {result.stderr}")
            return jsonify({'error': 'Metadata extraction failed.', 'details': result.stderr}), 500

        video_info = json.loads(result.stdout)
        original_title = video_info.get('title', 'video')
        safe_title = safe_filename(original_title)
        display_title = sanitize_title(original_title)
        logger.info(f"[Video] Title: {original_title}, requested quality: {video_quality}")

        temp_dir = Path('temp')
        temp_dir.mkdir(exist_ok=True)
        output_file = temp_dir / f"{safe_title}_{cache_buster}.mp4"

        format_worked = False
        for format_code in format_codes:
            try:
                yt_dlp_command = (
                    f'yt-dlp -f "{format_code}" --merge-output-format mp4 '
                    f'--no-playlist {JS_ARGS} {cookies_arg} '
                    f'-o "{output_file}" "{song_url}"'
                )
                logger.info(f"[Video] Trying format: {format_code}")
                result = subprocess.run(yt_dlp_command, shell=True, capture_output=True, text=True)
                if result.stderr:
                    logger.info(f"[Video] stderr: {result.stderr}")
                if output_file.exists() and output_file.stat().st_size > 0:
                    format_worked = True
                    break
            except Exception as e:
                logger.error(f"[Video] Format {format_code} failed: {e}")

        if not format_worked:
            return jsonify({'error': 'Failed to download the video with any format.'}), 500

        download_name = f"{display_title} [{video_quality}].mp4"

        response = send_file(
            str(output_file),
            as_attachment=True,
            download_name=download_name,
            mimetype='video/mp4'
        )

        @after_this_request
        def cleanup(response):
            if output_file.exists():
                output_file.unlink()
                logger.info(f"[Video] Cleaned up temp file: {output_file}")
            return response
        return response

    except Exception as e:
        logger.error(f"[Video] Error in /download/video: {str(e)}")
        if output_file and output_file.exists():
            output_file.unlink()
        return jsonify({'error': 'Failed to download the video.', 'details': str(e)}), 500
