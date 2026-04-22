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
        logger.error(f"[Audio] Invalid or missing YouTube URL: {song_url}")
        return jsonify({'error': 'Please provide a valid YouTube URL.'}), 400

    valid_audio_qualities = ['128K', '192K', '320K']
    audio_quality = quality if quality in valid_audio_qualities else '192K'
    output_file = None
    try:
        cookies_file = Path('cookies.txt')
        if not cookies_file.exists():
            logger.error(f"[Audio] Cookies file not found at {cookies_file}")
            return jsonify({'error': 'Cookies file missing, can\'t authenticate with YouTube.'}), 500

        metadata_command = f'yt-dlp --dump-json --cookies "{cookies_file}" --js-runtimes node --remote-components ejs:github "{song_url}"'
        logger.info(f"[Audio] Fetching metadata for URL: {song_url}, cacheBuster: {cache_buster}")
        result = subprocess.run(metadata_command, shell=True, capture_output=True, text=True)
        if result.stderr:
            logger.error(f"[Audio] Metadata fetch stderr: {result.stderr}")
        video_info = json.loads(result.stdout)
        video_title = re.sub(r'[^a-zA-Z0-9]', '_', video_info['title'])
        logger.info(f"[Audio] Video title: {video_info['title']}, quality: {audio_quality}")

        temp_dir = Path('temp')
        temp_dir.mkdir(exist_ok=True)
        output_file = temp_dir / f"{video_title}_{audio_quality}_{cache_buster}.mp3"

        yt_dlp_command = f'yt-dlp -x --audio-format mp3 --audio-quality {audio_quality} --cookies "{cookies_file}" --js-runtimes node --remote-components ejs:github -o "{output_file}" "{song_url}"'
        logger.info(f"[Audio] Running yt-dlp command: {yt_dlp_command}")
        result = subprocess.run(yt_dlp_command, shell=True, capture_output=True, text=True)
        logger.info(f"[Audio] yt-dlp stdout: {result.stdout}")
        logger.info(f"[Audio] yt-dlp stderr: {result.stderr}")

        if not output_file.exists():
            logger.error('[Audio] Output file not found after yt-dlp command.')
            return jsonify({'error': 'Failed to download the audio.'}), 500

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
                logger.info(f"[Audio] Cleaned up temp file: {output_file}")
            return response
        return response
    except Exception as e:
        logger.error(f"[Audio] Error in /download/audio: {str(e)}")
        if output_file and output_file.exists():
            output_file.unlink()
            logger.info(f"[Audio] Cleaned up temp file on error: {output_file}")
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
        '144p': ['160+251', '133+251', '134+251'],
        '240p': ['133+251', '134+251', '135+251'],
        '360p': ['18', '134+251', '135+251', '136+251'],
        '480p': ['135+251', '136+251', '137+251'],
        '720p': ['136+251', '137+251', '135+251'],
        '1080p': ['137+251', '136+251', '135+251'],
    }
    format_codes = quality_format_map.get(video_quality, ['137+251', '136+251', '135+251'])

    output_file = None
    try:
        cookies_file = Path('cookies.txt')
        if not cookies_file.exists():
            logger.error(f"[Video] Cookies file not found at {cookies_file}")
            return jsonify({'error': 'Cookies file missing, can\'t authenticate with YouTube.'}), 500

        metadata_command = f'yt-dlp --dump-json --cookies "{cookies_file}" --js-runtimes node --remote-components ejs:github "{song_url}"'
        logger.info(f"[Video] Fetching metadata for URL: {song_url}, cacheBuster: {cache_buster}")
        result = subprocess.run(metadata_command, shell=True, capture_output=True, text=True)
        if result.stderr:
            logger.error(f"[Video] Metadata fetch stderr: {result.stderr}")
        if not result.stdout.strip():
            return jsonify({'error': 'Metadata extraction failed - page needs reload', 'details': result.stderr}), 500
        video_info = json.loads(result.stdout)

        video_title = re.sub(r'[^a-zA-Z0-9]', '_', video_info['title'])
        logger.info(f"[Video] Video title: {video_info['title']}, requested quality: {video_quality}")

        temp_dir = Path('temp')
        temp_dir.mkdir(exist_ok=True)
        output_file = temp_dir / f"{video_title}_{video_quality}_{cache_buster}.mp4"

        formats_command = f'yt-dlp --list-formats --cookies "{cookies_file}" --js-runtimes node --remote-components ejs:github "{song_url}"'
        logger.info(f"[Video] Fetching available formats: {formats_command}")
        result = subprocess.run(formats_command, shell=True, capture_output=True, text=True)

        available_formats = result.stdout
        adjusted_format_codes = [code for code in format_codes if code.split('+')[0] in available_formats]
        if not adjusted_format_codes:
            logger.warning(f"[Video] Requested formats not available. Falling back.")
            adjusted_format_codes = ['bestvideo[height<=720]+bestaudio/best', 'bestvideo[height<=480]+bestaudio/best', 'best']

        logger.info(f"[Video] Using format codes: {', '.join(adjusted_format_codes)}")

        user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'
        format_worked = False

        for format_code in adjusted_format_codes:
            try:
                yt_dlp_command = f'yt-dlp --user-agent "{user_agent}" -f "{format_code}" --merge-output-format mp4 --cookies "{cookies_file}" --js-runtimes node --remote-components ejs:github -o "{output_file}" "{song_url}"'
                logger.info(f"[Video] Running yt-dlp with format {format_code}")
                result = subprocess.run(yt_dlp_command, shell=True, capture_output=True, text=True)
                logger.info(f"[Video] yt-dlp stdout: {result.stdout}")
                logger.info(f"[Video] yt-dlp stderr: {result.stderr}")

                if output_file.exists():
                    format_worked = True
                    break
            except Exception as e:
                logger.error(f"[Video] Format {format_code} failed: {e}")

        if not format_worked:
            return jsonify({'error': 'Failed to download the video with any format.'}), 500

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
                logger.info(f"[Video] Cleaned up temp file: {output_file}")
            return response
        return response

    except Exception as e:
        logger.error(f"[Video] Error in /download/video: {str(e)}")
        if output_file and output_file.exists():
            output_file.unlink()
        return jsonify({'error': 'Failed to download the video.', 'details': str(e)}), 500
