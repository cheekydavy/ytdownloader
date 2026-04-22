from flask import Blueprint, request, send_file, Response
import yt_dlp
import os
import tempfile
import logging

x_routes = Blueprint('x', __name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@x_routes.route('/api/xurl')
def download():
    url = request.args.get('url')
    if not url:
        logger.error("Missing URL parameter")
        return Response('Missing URL parameter', status=400)

    if not ("x.com" in url or "twitter.com" in url):
        logger.error(f"Invalid Twitter/X URL: {url}")
        return Response('URL must be from x.com or twitter.com', status=400)

    ydl_opts = {
        'outtmpl': '%(id)s.%(ext)s',
        'format': 'best',
        'no_cache_dir': True,
        'quiet': True,
    }

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            ydl_opts['outtmpl'] = f'{tmpdir}/%(id)s.%(ext)s'
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                if not os.path.exists(filename):
                    logger.error(f"File not found: {filename}")
                    return Response('Error: Video file not found', status=500)
                return send_file(
                    filename,
                    as_attachment=True,
                    download_name=os.path.basename(filename),
                    mimetype='video/mp4'
                )
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        return Response(f'Error: {str(e)}', status=500)
