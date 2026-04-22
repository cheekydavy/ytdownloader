from flask import Flask
import os

from modules.youtube import youtube_routes
from modules.tiktok import tiktok_routes
from modules.instagram import instagram_routes
from modules.facebook import facebook_routes
from modules.x import x_routes

app = Flask(__name__)

app.register_blueprint(youtube_routes, url_prefix='/')
app.register_blueprint(tiktok_routes, url_prefix='/')
app.register_blueprint(instagram_routes, url_prefix='/')
app.register_blueprint(facebook_routes, url_prefix='/')
app.register_blueprint(x_routes, url_prefix='/')

@app.route('/')
def home():
    return (
        'Combined Downloader API. Available endpoints:\n'
        '/download/audio, /download/video (YouTube)\n'
        '/api/tiktokurl, /api/tiktoaudio (TikTok)\n'
        '/download/iglink (Instagram)\n'
        '/api/fburl (Facebook)\n'
        '/api/xurl (X / Twitter)'
    )

@app.route('/health')
def health():
    return 'ok'

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
