from flask import Blueprint, request, send_file, Response, redirect
import yt_dlp
import os
import tempfile
import logging
from playwright.sync_api import sync_playwright

instagram_routes = Blueprint('instagram', __name__)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
        logger.error(f"yt-dlp failed: {str(e)}. Using fallback Playwright.")

        fallback_url = get_saveinsta_download_url(url)
        if fallback_url:
            logger.info(f"Redirecting to fallback download URL: {fallback_url}")
            return redirect(fallback_url)
        else:
            return Response('Error: Could not retrieve fallback download URL.', status=500)
