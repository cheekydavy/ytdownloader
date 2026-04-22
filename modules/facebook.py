from flask import Blueprint, request, send_file, Response
import yt_dlp
import os
import tempfile

facebook_routes = Blueprint('facebook', __name__)


@facebook_routes.route('/api/fburl')
def download():
    url = request.args.get('url')
    if not url:
        return Response('Missing URL parameter', status=400)

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
                return send_file(
                    filename,
                    as_attachment=True,
                    download_name=os.path.basename(filename)
                )
    except Exception as e:
        return Response(f'Error: {str(e)}', status=500)
