from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse
import asyncio
import yt_dlp
import uuid
import logging
from pathlib import Path
from typing import AsyncGenerator
import json
import aiohttp

router = APIRouter()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def cleanup_file(file_path: Path):
    """Background task to cleanup temporary files"""
    try:
        if file_path.exists():
            file_path.unlink()
            logger.info(f"Cleaned up temp file: {file_path}")
    except Exception as e:
        logger.error(f"Failed to cleanup {file_path}: {e}")

async def get_instagram_info_and_url(url: str) -> tuple[str, str, str]:
    """Get Instagram info and direct URL using JSON output"""
    cmd = [
        "yt-dlp",
        "--dump-json",
        "--quiet",
        "--no-warnings",
        "-f", "best",
        url
    ]
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    stdout, stderr = await process.communicate()
    
    if stderr and "ERROR" in stderr.decode():
        logger.error(f"Instagram yt-dlp error: {stderr.decode()}")
        raise HTTPException(status_code=500, detail="Failed to get Instagram info")
    
    if not stdout.strip():
        raise HTTPException(status_code=500, detail="No Instagram info received")
    
    try:
        info = json.loads(stdout.decode())
        
        direct_url = info.get('url')
        if not direct_url or not direct_url.startswith('http'):
            raise HTTPException(status_code=500, detail="No valid Instagram URL found")
        
        title = info.get('title', 'instagram_media')
        ext = info.get('ext', 'mp4')
        
        logger.info(f"Got Instagram direct URL: {direct_url[:100]}...")
        
        return direct_url, title, ext
        
    except json.JSONDecodeError as e:
        logger.error(f"Instagram JSON decode error: {e}")
        raise HTTPException(status_code=500, detail="Failed to parse Instagram info")

async def stream_from_url(url: str, chunk_size: int = 2097152) -> AsyncGenerator[bytes, None]:
    """Stream content directly from URL with 2MB chunks and Instagram-specific headers"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'identity',
        'Referer': 'https://www.instagram.com/',
        'Origin': 'https://www.instagram.com',
        'Sec-Fetch-Dest': 'video',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'cross-site'
    }
    
    timeout = aiohttp.ClientTimeout(total=None, connect=30)
    
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        try:
            async with session.get(url, allow_redirects=True) as response:
                if response.status not in [200, 206]:
                    raise HTTPException(status_code=500, detail=f"Failed to fetch Instagram media: HTTP {response.status}")
                
                async for chunk in response.content.iter_chunked(chunk_size):
                    yield chunk
                    
        except aiohttp.ClientError as e:
            logger.error(f"Instagram streaming error: {e}")
            raise HTTPException(status_code=500, detail=f"Streaming error: {str(e)}")

# ORIGINAL ENDPOINT (KEEP AS-IS)
@router.get("/download/iglink")
async def download_instagram_media(
    background_tasks: BackgroundTasks,
    url: str = Query(..., description="Instagram URL")
):
    """Download Instagram media (video/image) - Original endpoint"""
    if not (url.startswith('https://www.instagram.com/') or url.startswith('https://instagr.am/')):
        raise HTTPException(status_code=400, detail="Invalid Instagram URL")
    
    try:
        # Create temp directory
        temp_dir = Path('temp')
        temp_dir.mkdir(exist_ok=True)
        
        # Generate unique filename
        filename = f"{uuid.uuid4()}.%(ext)s"
        output_template = str(temp_dir / filename)
        
        ydl_opts = {
            'outtmpl': output_template,
            'format': 'best',
            'merge_output_format': 'mp4',
            'no_cache_dir': True,
            'quiet': True,
        }
        
        loop = asyncio.get_event_loop()
        
        def download_media():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                actual_filename = ydl.prepare_filename(info)
                return actual_filename, info
        
        actual_filename, info = await loop.run_in_executor(None, download_media)
        output_path = Path(actual_filename)
        
        if not output_path.exists():
            raise HTTPException(status_code=500, detail="Download failed - file not found")
        
        # Determine media type and filename
        title = info.get('title', 'instagram_media')
        ext = output_path.suffix or '.mp4'
        media_type = 'video/mp4' if ext in ['.mp4', '.mov'] else 'image/jpeg'
        
        # Schedule cleanup
        background_tasks.add_task(cleanup_file, output_path)
        
        return FileResponse(
            path=str(output_path),
            filename=f"{title}{ext}",
            media_type=media_type
        )
        
    except Exception as e:
        logger.error(f"Instagram download error: {e}")
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")

# NEW STREAMING ENDPOINT (FOR WEBSITE)
@router.get("/stream/iglink")
async def stream_instagram_media(
    url: str = Query(..., description="Instagram URL")
):
    """Stream Instagram media with browser progress"""
    if not (url.startswith('https://www.instagram.com/') or url.startswith('https://instagr.am/')):
        raise HTTPException(status_code=400, detail="Invalid Instagram URL")
    
    try:
        # Get direct URL and info
        direct_url, title, ext = await get_instagram_info_and_url(url)
        
        # Determine media type
        media_type = 'video/mp4' if ext in ['mp4', 'mov'] else 'image/jpeg'
        
        return StreamingResponse(
            stream_from_url(direct_url, chunk_size=2097152),  # 2MB chunks
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{title}.{ext}"',
                "Cache-Control": "no-cache",
                "Accept-Ranges": "bytes"
            }
        )
        
    except Exception as e:
        logger.error(f"Instagram stream error: {e}")
        raise HTTPException(status_code=500, detail=f"Stream failed: {str(e)}")
