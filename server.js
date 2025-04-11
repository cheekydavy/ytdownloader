const express = require('express');
const ytdl = require('@distube/ytdl-core');
const { pipeline } = require('stream');
const yts = require('yt-search');
const ffmpeg = require('ffmpeg-static');

const app = express();
const port = process.env.PORT || 3000;

app.use(express.urlencoded({ extended: true }));

app.get('/', (req, res) => {
    res.send('YouTube Audio Downloader API. Use /download?song=<song_name> to download audio.');
});

app.get('/download', async (req, res) => {
    const songName = req.query.song;

    if (!songName || typeof songName !== 'string' || songName.trim() === '') {
        return res.status(400).json({ error: 'Please provide a valid song name.' });
    }

    try {
        // Search YouTube for the song
        const searchResults = await yts(songName);
        const video = searchResults.videos[0];

        if (!video) {
            return res.status(404).json({ error: 'No videos found for this song.' });
        }

        const videoUrl = video.url;
        const videoTitle = video.title.replace(/[^a-zA-Z0-9]/g, '_');

        // Validate video duration (max 10 minutes)
        if (video.seconds > 600) {
            return res.status(400).json({ error: 'Video is too long (max 10 minutes).' });
        }

        // Check if the video is accessible before downloading
        let videoInfo;
        try {
            videoInfo = await ytdl.getBasicInfo(videoUrl);
            console.log('Video title:', videoInfo.videoDetails.title);
        } catch (err) {
            console.error('getBasicInfo error:', err);
            return res.status(500).json({ error: 'Failed to access video info. The video may be unavailable or restricted.' });
        }

        // Download audio stream
        let audioStream;
        try {
            audioStream = ytdl(videoUrl, { quality: 'highestaudio', filter: 'audioonly' });
        } catch (err) {
            console.error('ytdl error:', err);
            return res.status(500).json({ error: 'Failed to fetch audio stream from YouTube. The video may be unavailable or restricted.' });
        }

        // Set headers for file download
        res.setHeader('Content-Disposition', `attachment; filename="${videoTitle}.mp3"`);
        res.setHeader('Content-Type', 'audio/mpeg');

        // Stream audio directly to FFmpeg and then to the response
        const ffmpegProcess = require('child_process').spawn(ffmpeg, [
            '-i', 'pipe:0',
            '-vn',
            '-ar', '44100',
            '-ac', '2',
            '-b:a', '192k',
            'pipe:1'
        ], { stdio: ['pipe', 'pipe', 'pipe'] });

        // Pipe the audio stream to FFmpeg
        pipeline(audioStream, ffmpegProcess.stdin, (err) => {
            if (err) {
                console.error('Pipeline error:', err);
                if (!res.headersSent) {
                    res.status(500).json({ error: 'Failed to process audio stream.' });
                }
            }
        });

        // Pipe FFmpeg output to the response
        pipeline(ffmpegProcess.stdout, res, (err) => {
            if (err) {
                console.error('Streaming error:', err);
                if (!res.headersSent) {
                    res.status(500).json({ error: 'Error streaming the audio file.' });
                }
            }
        });

        ffmpegProcess.stderr.on('data', (data) => {
            console.error('FFmpeg error:', data.toString());
        });

        ffmpegProcess.on('error', (err) => {
            console.error('FFmpeg process error:', err);
            if (!res.headersSent) {
                res.status(500).json({ error: 'Failed to convert audio.' });
            }
        });

    } catch (error) {
        console.error('Error:', error);
        if (!res.headersSent) {
            res.status(500).json({ error: 'Failed to search, download, or convert the audio.' });
        }
    }
});

app.listen(port, () => {
    console.log(`Server running on port ${port}`);
});
