from flask import Blueprint, request, jsonify, send_file, after_this_request
import subprocess
import os
import re
import json
import logging
import shutil
import threading
import time
import uuid
from pathlib import Path
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

# Only the 11-character video id is ever taken from the request. The URL handed to yt-dlp is rebuilt
# from it, so nothing else the client sends can reach the command line.
YT_URL_RE = re.compile(
    r'^https?://(?:www\.)?(?:youtube\.com|youtu\.be)/(?:watch\?v=|shorts/|embed/)?([A-Za-z0-9_-]{11})(?:\?.*)?$'
)

def extract_video_id(url):
    if not isinstance(url, str):
        return None
    m = YT_URL_RE.match(url)
    return m.group(1) if m else None

def is_valid_youtube_url(url):
    return extract_video_id(url) is not None

def sanitize_title(title):
    clean = re.sub(r'[\\/:*?"<>|]', '', title)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean or 'audio'

JS_ARGS = ['--js-runtimes', 'node', '--remote-components', 'ejs:github']

# A yt-dlp run (node + ffmpeg) is memory hungry, so cap how many run at once per gunicorn worker.
MAX_CONCURRENT = int(os.environ.get('YTDLP_MAX_CONCURRENT', '2'))
_slots = threading.BoundedSemaphore(MAX_CONCURRENT)
SLOT_WAIT_SECONDS = int(os.environ.get('YTDLP_SLOT_WAIT', '120'))
RUN_TIMEOUT_SECONDS = int(os.environ.get('YTDLP_TIMEOUT', '540'))

TEMP_DIR = Path('temp')
VALID_AUDIO_QUALITIES = ['128K', '192K', '320K']
VALID_VIDEO_QUALITIES = ['144p', '240p', '360p', '480p', '720p', '1080p']

# Same preference order as before, but joined into ONE yt-dlp format selector (a/b/c), so a missing
# format falls through inside a single run instead of restarting the whole extraction.
QUALITY_FORMATS = {
    '144p': ['160+140', '160+251', 'bestvideo[height<=144]+bestaudio/best'],
    '240p': ['133+140', '133+251', 'bestvideo[height<=240]+bestaudio/best'],
    '360p': ['18', '134+140', '134+251', 'bestvideo[height<=360]+bestaudio/best'],
    '480p': ['135+140', '135+251', 'bestvideo[height<=480]+bestaudio/best'],
    '720p': ['22', '136+140', '136+251', 'bestvideo[height<=720]+bestaudio/best'],
    '1080p': ['137+140', '137+251', 'bestvideo[height<=1080]+bestaudio/best'],
}


def _cookie_args(job):
    """yt-dlp rewrites the cookie file it is given, so every job works on its own copy."""
    src = Path('cookies.txt')
    if not src.exists():
        return [], None
    copy = TEMP_DIR / f'{job}.cookies.txt'
    shutil.copyfile(src, copy)
    return ['--cookies', str(copy)], copy


def _cleanup(job):
    for p in TEMP_DIR.glob(f'{job}*'):
        try:
            p.unlink()
        except Exception:
            pass


def _run(args):
    return subprocess.run(['yt-dlp'] + args, capture_output=True, text=True, timeout=RUN_TIMEOUT_SECONDS)


def _parse_title(stdout, default):
    """--print '%(title)j' emits the title as one JSON string line."""
    for line in (stdout or '').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
            if isinstance(value, str) and value.strip():
                return value
        except ValueError:
            continue
    return default


def _find_output(job, preferred_ext):
    preferred = TEMP_DIR / f'{job}.{preferred_ext}'
    if preferred.exists() and preferred.stat().st_size > 0:
        return preferred
    return None


@youtube_routes.route('/download/audio', methods=['GET'])
@limiter.limit("500 per 15min")
def download_audio():
    song_url = request.args.get('song')
    quality = request.args.get('quality')
    fast = request.args.get('fast') == '1'  # caller embeds the cover art itself: skip the thumbnail step
    video_id = extract_video_id(song_url)
    if not video_id:
        logger.error(f"[Audio] Invalid or missing YouTube URL: {song_url!r}")
        return jsonify({'error': 'Please provide a valid YouTube URL.'}), 400

    audio_quality = quality if quality in VALID_AUDIO_QUALITIES else '192K'
    canonical_url = f'https://www.youtube.com/watch?v={video_id}'

    if not _slots.acquire(timeout=SLOT_WAIT_SECONDS):
        return jsonify({'error': 'Server busy, try again shortly.'}), 503

    job = uuid.uuid4().hex
    try:
        TEMP_DIR.mkdir(exist_ok=True)
        cookies_args, _ = _cookie_args(job)

        args = ['-x', '--audio-format', 'mp3', '--audio-quality', audio_quality]
        if not fast:
            args += ['--embed-thumbnail', '--convert-thumbnails', 'jpg']
        args += [
            '--no-playlist', '--no-simulate', '--print', '%(title)j', '-N', '4',
            *JS_ARGS, *cookies_args,
            '-o', str(TEMP_DIR / f'{job}.%(ext)s'),
            canonical_url,
        ]

        started = time.time()
        logger.info(f"[Audio] {video_id} quality={audio_quality} fast={fast}")
        result = _run(args)
        if result.stderr:
            logger.info(f"[Audio] yt-dlp stderr: {result.stderr[-1500:]}")

        output_file = _find_output(job, 'mp3')
        if not output_file:
            logger.error('[Audio] Output file not found after yt-dlp command.')
            _cleanup(job)
            return jsonify({'error': 'Failed to download the audio.', 'details': (result.stderr or '')[-800:]}), 500

        title = _parse_title(result.stdout, 'audio')
        logger.info(f"[Audio] done in {time.time() - started:.1f}s: {title}")

        response = send_file(
            str(output_file),
            as_attachment=True,
            download_name=f"{sanitize_title(title)}.mp3",
            mimetype='audio/mpeg'
        )

        @after_this_request
        def cleanup(resp):
            _cleanup(job)
            return resp
        return response
    except subprocess.TimeoutExpired:
        logger.error('[Audio] yt-dlp timed out')
        _cleanup(job)
        return jsonify({'error': 'Failed to download the audio.', 'details': 'timed out'}), 504
    except Exception as e:
        logger.error(f"[Audio] Error in /download/audio: {str(e)}")
        _cleanup(job)
        return jsonify({'error': 'Failed to download the audio.', 'details': str(e)}), 500
    finally:
        _slots.release()


@youtube_routes.route('/download/video', methods=['GET'])
@limiter.limit("500 per 15min")
def download_video():
    song_url = request.args.get('song')
    quality = request.args.get('quality')
    video_id = extract_video_id(song_url)
    if not video_id:
        logger.error(f"[Video] Invalid or missing YouTube URL: {song_url!r}")
        return jsonify({'error': 'Please provide a valid YouTube URL.'}), 400

    video_quality = quality if quality in VALID_VIDEO_QUALITIES else '1080p'
    format_selector = '/'.join(QUALITY_FORMATS[video_quality])
    canonical_url = f'https://www.youtube.com/watch?v={video_id}'

    if not _slots.acquire(timeout=SLOT_WAIT_SECONDS):
        return jsonify({'error': 'Server busy, try again shortly.'}), 503

    job = uuid.uuid4().hex
    try:
        TEMP_DIR.mkdir(exist_ok=True)
        cookies_args, _ = _cookie_args(job)

        args = [
            '-f', format_selector,
            '--merge-output-format', 'mp4', '--remux-video', 'mp4',
            '--no-playlist', '--no-simulate', '--print', '%(title)j', '-N', '4',
            *JS_ARGS, *cookies_args,
            '-o', str(TEMP_DIR / f'{job}.%(ext)s'),
            canonical_url,
        ]

        started = time.time()
        logger.info(f"[Video] {video_id} quality={video_quality}")
        result = _run(args)
        if result.stderr:
            logger.info(f"[Video] yt-dlp stderr: {result.stderr[-1500:]}")

        output_file = _find_output(job, 'mp4')
        if not output_file:
            logger.error('[Video] Output file not found after yt-dlp command.')
            _cleanup(job)
            return jsonify({'error': 'Failed to download the video with any format.', 'details': (result.stderr or '')[-800:]}), 500

        title = _parse_title(result.stdout, 'video')
        logger.info(f"[Video] done in {time.time() - started:.1f}s: {title}")

        response = send_file(
            str(output_file),
            as_attachment=True,
            download_name=f"{sanitize_title(title)} [{video_quality}].mp4",
            mimetype='video/mp4'
        )

        @after_this_request
        def cleanup(resp):
            _cleanup(job)
            return resp
        return response
    except subprocess.TimeoutExpired:
        logger.error('[Video] yt-dlp timed out')
        _cleanup(job)
        return jsonify({'error': 'Failed to download the video.', 'details': 'timed out'}), 504
    except Exception as e:
        logger.error(f"[Video] Error in /download/video: {str(e)}")
        _cleanup(job)
        return jsonify({'error': 'Failed to download the video.', 'details': str(e)}), 500
    finally:
        _slots.release()
