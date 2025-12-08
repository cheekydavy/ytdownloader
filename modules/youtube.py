from flask import Blueprint, request, jsonify, send_file, after_this_request
import subprocess
import os
import re
import json
import logging
from pathlib import Path
import time
import flask_limiter  # Added this line
from flask_limiter.util import get_remote_address  # Added this line

youtube_routes = Blueprint('youtube', __name__)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Rate-limit requests to avoid hitting YouTube's limits
limiter = flask_limiter.Limiter(  # Updated to use flask_limiter.Limiter
    key_func=get_remote_address,
    default_limits=["500 per 15min"]
)

# Initialize limiter with Flask app (will be set when blueprint is registered)
def init_limiter(app):
    limiter.init_app(app)

# Validate YouTube URL
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
            return jsonify({'error': 'Cookies file missing, can’t authenticate with YouTube.'}), 500

        # Fetch video metadata using yt-dlp
        metadata_command = f'yt-dlp --dump-json --cookies "{cookies_file}" "{song_url}"'
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

        yt_dlp_command = f'yt-dlp -x --audio-format mp3 --audio-quality {audio_quality} --cookies "{cookies_file}" -o "{output_file}" "{song_url}"'
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

    valid_video_qualities = ['144p', '240p', '360p', '480p', '720p', '1080p']
    video_quality = quality if quality in valid_video_qualities else '1080p'

    output_file = None
    try:
        # 1. Define Filter and User Agent
        video_height = video_quality.strip('p') 
        format_filter = f'bestvideo[height<={video_height}]+bestaudio/best'
        user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'

        cookies_file = Path('cookies.txt')
        if not cookies_file.exists():
            logger.error(f"[Video] Cookies file not found at {cookies_file}")
            return jsonify({'error': 'Cookies file missing, can’t authenticate with YouTube.'}), 500

        # 2. Fetch video metadata (REQUIRED to get the title and define the output path)
        metadata_command = f'yt-dlp --dump-json --cookies "{cookies_file}" "{song_url}"'
        logger.info(f"[Video] Fetching metadata for URL: {song_url}, cacheBuster: {cache_buster}")
        result = subprocess.run(metadata_command, shell=True, capture_output=True, text=True)
        
        if result.stderr and "WARNING" not in result.stderr:
             # Only log errors that are not warnings to keep things clean
            logger.error(f"[Video] Metadata fetch stderr: {result.stderr}")
        
        if not result.stdout:
            logger.error(f"[Video] Failed to retrieve video metadata. Output: {result.stderr}")
            return jsonify({'error': 'Video metadata could not be retrieved. Video may be private or removed.'}), 500

        video_info = json.loads(result.stdout)
        video_title = re.sub(r'[^a-zA-Z0-9]', '_', video_info['title'])
        logger.info(f"[Video] Video title: {video_info['title']}, requested quality: {video_quality}")

        temp_dir = Path('temp')
        temp_dir.mkdir(exist_ok=True)
        output_file = temp_dir / f"{video_title}_{video_quality}_{cache_buster}.mp4"

        # 3. Run the robust download command
        yt_dlp_command = (
            f'yt-dlp --user-agent "{user_agent}" '
            f'-f "{format_filter}" ' # Using the dynamic filter
            '--merge-output-format mp4 '
            f'--cookies "{cookies_file}" '
            f'-o "{output_file}" "{song_url}"'
        )
        logger.info(f"[Video] Running yt-dlp command with filter {format_filter}: {yt_dlp_command}")
        result = subprocess.run(yt_dlp_command, shell=True, capture_output=True, text=True)
        logger.info(f"[Video] yt-dlp stdout: {result.stdout}")
        logger.info(f"[Video] yt-dlp stderr: {result.stderr}")

        if not output_file.exists():
            logger.error('[Video] Output file not found after yt-dlp command.')
            logger.error(f"[Video] Final download attempt failed. STDERR: {result.stderr}")
            return jsonify({'error': 'Failed to download the video. Check logs for 404 or Signature errors.'}), 500

        logger.info(f"[Video] Successfully downloaded with filter {format_filter}")

        # 4. Final response and cleanup
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
            logger.info(f"[Video] Cleaned up temp file on error: {output_file}")
        return jsonify({'error': 'Failed to download the video.', 'details': str(e)}), 500
