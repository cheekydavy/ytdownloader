from flask import Flask
from modules.youtube import youtube_routes
from modules.tiktok import tiktok_routes
from modules.instagram import instagram_routes
from modules.facebook import facebook_routes

app = Flask(__name__)

# Register blueprints for each downloader
app.register_blueprint(youtube_routes, url_prefix='/')
app.register_blueprint(tiktok_routes, url_prefix='/')
app.register_blueprint(instagram_routes, url_prefix='/')
app.register_blueprint(facebook_routes, url_prefix='/')

@app.route('/')
def home():
    return 'Combined Downloader API. Available endpoints: /download/audio, /download/video (YouTube), /api/tiktokurl, /api/tiktoaudio (TikTok), /download/iglink (Instagram), /api/fburl (Facebook)'

@app.route('/health')
def health():
    return 'ok'

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
