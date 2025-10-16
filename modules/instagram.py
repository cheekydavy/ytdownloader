from flask import Blueprint, request, send_file, Response, redirect
import yt_dlp
import os
import tempfile
import logging
from apify_client import ApifyClient

instagram_routes = Blueprint('instagram', __name__)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Apify client with your API token (set via environment variable for security)
api_token = os.environ.get('APIFY_API_TOKEN', '<YOUR_API_TOKEN>')
client = ApifyClient(api_token)

def download_via_apify(ig_url):
    """Download video using Apify Instagram Scraper."""
    try:
        run_input = {
            "startUrls": [{"url": ig_url}],
            "proxy": {"useApifyProxy": True},
            "maxRequestRetries": 10,
            "downloadVideos": True  # Ensure video URLs are included
        }
        
        # Run the Actor and wait for it to finish
        run = client.actor("l5Rb0b8v9jFW4VrWh").call(run_input=run_input)
        dataset_id = run["defaultDatasetId"]
        
        # Poll for results
        for attempt in range(10):  # Max 50s wait
            items = client.dataset(dataset_id).iterate_items()
            for item in items:
                video_url = item.get("videoUrl") or item.get("media", [{}])[0].get("videoUrl")
                if video_url:
                    logger.info(f"Apify retrieved video URL: {video_url}")
                    return video_url
            time.sleep(5)  # Check every 5s
        logger.error("Apify run timed out or no video URL found")
        return None
    except Exception as e:
        logger.error(f"Apify failed: {str(e)}")
        return None

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

    # Primary: Apify
    video_url = download_via_apify(url)
    if video_url:
        logger.info(f"Redirecting to Apify video URL: {video_url}")
        return redirect(video_url)

    # Fallback: yt-dlp
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
        logger.error(f"yt-dlp failed: {str(e)}")
        return Response('Error: Could not retrieve video.', status=500)