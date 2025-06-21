from flask import Blueprint, request, send_file, Response
import yt_dlp
import os
import tempfile
import logging

instagram_routes = Blueprint('instagram', __name__)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@instagram_routes.route('/download/iglink')
def download():
    url = request.args.get('url')
    if not url:
        logger.error("Missing URL parameter")
        return Response('Missing URL parameter', status=400)

    if not (url.startswith('https://www.instagram.com/') or url.startswith('https://instagr.am/')):
        logger.error(f"Invalid Instagram URL: {url}")
        return Response('URL must be from instagram.com', status=400)

    ydl_opts = {
        'outtmpl': '%(id)s.%(ext)s',
        'format': 'best',
        'merge_output_format': 'mp4',
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
                    download_name=f"{info.get('title', 'video')}.mp4",
                    mimetype='video/mp4'
                )
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        return Response(f'Error: {str(e)}', status=500)
