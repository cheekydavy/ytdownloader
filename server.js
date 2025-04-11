const express = require('express');
const ytdl = require('@distube/ytdl-core');
const { pipeline } = require('stream');
const yts = require('yt-search');
const ffmpeg = require('ffmpeg-static');
const rateLimit = require('express-rate-limit'); // For rate-limiting

const app = express();
const port = process.env.PORT || 3000;

// Rate-limit requests to avoid hitting YouTube's limits
const limiter = rateLimit({
    windowMs: 15 * 60 * 1000, // 15 minutes
    max: 100, // Limit each IP to 100 requests per window
    message: 'Too many requests, please try again later.',
});
app.use('/download', limiter);

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
        // Search YouTube for the song, prioritize official audio
        const searchResults = await yts(`${songName} official audio`);
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

        // Add a user-agent to make requests look like they're from a browser
        const requestOptions = {
            requestOptions: {
                headers: {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                }
            }
        };

        // Check if the video is accessible before downloading, with retry logic for 429
        let videoInfo;
        let retries = 3;
        while (retries > 0) {
            try {
                videoInfo = await ytdl.getBasicInfo(videoUrl, requestOptions);
                console.log('Video title:', videoInfo.videoDetails.title);
                break; // Success, exit retry loop
            } catch (err) {
                console.error('getBasicInfo error:', err);
                if (err.statusCode === 429) {
                    retries--;
                    if (retries === 0) {
                        return res.status(429).json({ error: 'Rate limit exceeded. Please try again later.' });
                    }
                    console.log(`Rate limit hit, retrying (${retries} attempts left)...`);
                    await new Promise(resolve => setTimeout(resolve, 2000)); // Wait 2 seconds before retrying
                } else {
                    return res.status(500).json({ error: 'Failed to access video info. The video may be unavailable or restricted.' });
                }
            }
        }

        // Download audio stream
        let audioStream;
        try {
            audioStream = ytdl(videoUrl, { quality: 'highestaudio', filter: 'audioonly', ...requestOptions });
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
