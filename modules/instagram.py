from flask import Blueprint, request, send_file, Response, redirect
import yt_dlp
import os
import tempfile
import logging
import re
import glob
from playwright.sync_api import sync_playwright
import instaloader

instagram_routes = Blueprint('instagram', __name__)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_shortcode(url):
    """Extract Instagram shortcode from URL."""
    patterns = [
        r'/p/([A-Za-z0-9_-]+)',
        r'/reel/([A-Za-z0-9_-]+)'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def download_with_instaloader(url, tmpdir):
    """Download using instaloader."""
    shortcode = get_shortcode(url)
    if not shortcode:
        raise ValueError("Invalid Instagram URL: could not extract shortcode")

    L = instaloader.Instaloader(
        download_video_thumbnails=False,
        compress_json=False,
        post_metadata_txt_pattern=''
    )
    
    # Add login if credentials provided via environment variables
    username = os.environ.get('INSTAGRAM_USERNAME')
    password = os.environ.get('INSTAGRAM_PASSWORD')
    if username and password:
        try:
            L.login(username, password)
            logger.info("Successfully logged in to Instagram via instaloader.")
        except Exception as login_error:
            logger.warning(f"Instaloader login failed: {str(login_error)}. Proceeding without login.")
    
    post = instaloader.Post.from_shortcode(L.context, shortcode)
    
    if not post.is_video:
        raise ValueError("Post is not a video")
    
    L.download_post(post, target=tmpdir)
    
    # Find the MP4 file more robustly
    video_files = []
    for root, dirs, files in os.walk(tmpdir):
        for file in files:
            if file.endswith('.mp4'):
                video_files.append(os.path.join(root, file))
    
    if not video_files:
        raise FileNotFoundError("No video file found after download")
    
    # Use the most recent MP4 file
    filename = max(video_files, key=os.path.getctime)
    title = (post.caption or f"instagram_{post.shortcode}").replace('/', '_').replace('\\', '_')[:100]
    return filename, f"{title}.mp4"

def get_saveinsta_download_url(ig_url):
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto("https://saveinsta.to", timeout=60000)

            # Fill the IG URL in the input box
            page.fill("input[name='url']", ig_url)

            # Click the submit/download button (adjust selector if needed)
            page.click("button[type='submit']")

            # Wait for the download link to appear (adjust selector as needed)
            page.wait_for_selector("a[href^='https://dl.snapcdn.app']", timeout=60000)

            # Extract the download URL
            download_url = page.get_attribute("a[href^='https://dl.snapcdn.app']", "href")

            browser.close()
            return download_url
    except Exception as e:
        logger.error(f"Fallback Playwright error: {str(e)}")
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

    # Primary: instaloader (with optional login)
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            filename, download_name = download_with_instaloader(url, tmpdir)
            return send_file(
                filename,
                as_attachment=True,
                download_name=download_name,
                mimetype='video/mp4'
            )
    except Exception as e:
        logger.error(f"Instaloader failed: {str(e)}. Trying yt-dlp fallback.")

    # Fallback 1: yt-dlp
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            ydl_opts['outtmpl'] = f'{tmpdir}/%(id)s.%(ext)s'
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                if not os.path.exists(filename):
                    logger.error(f"File not found: {filename}")
                    raise FileNotFoundError('Video file not found')
                return send_file(
                    filename,
                    as_attachment=True,
                    download_name=f"{info.get('title', 'video')}.mp4",
                    mimetype='video/mp4'
                )
    except Exception as e:
        logger.error(f"yt-dlp failed: {str(e)}. Using saveinsta fallback.")

        # Fallback 2: Playwright (saveinsta)
        fallback_url = get_saveinsta_download_url(url)
        if fallback_url:
            logger.info(f"Redirecting to fallback download URL: {fallback_url}")
            return redirect(fallback_url)
        else:
            return Response('Error: Could not retrieve fallback download URL.', status=500)
