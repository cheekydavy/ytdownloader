const express = require('express');
const yts = require('yt-search');
const rateLimit = require('express-rate-limit');
const { exec } = require('child_process');
const fs = require('fs');
const path = require('path');
const { promisify } = require('util');

const app = express();
const port = process.env.PORT || 3000;
const execPromise = promisify(exec);

// Rate-limit requests to avoid hitting YouTube's limits
const limiter = rateLimit({
    windowMs: 15 * 60 * 1000, // 15 minutes
    max: 500, // Already increased to 500 requests per window
    message: 'Too many requests, please slow down.',
});
app.use('/download', limiter);

app.use(express.urlencoded({ extended: true }));
app.set('trust proxy', 1); // Trust Heroku's proxy to fix the rate limiter

app.get('/', (req, res) => {
    res.send('YouTube Downloader API. Use /download/audio?song=<song_name>&quality=<quality> to rip audio or /download/video?song=<song_name>&quality=<quality> to rip video.');
});

// Download audio endpoint
app.get('/download/audio', async (req, res) => {
    const songName = req.query.song;
    const quality = req.query.quality;

    if (!songName || typeof songName !== 'string' || songName.trim() === '') {
        return res.status(400).json({ error: 'Please provide a song name.' });
    }

    // Validate quality parameter
    const validAudioQualities = ['128K', '192K', '320K'];
    const audioQuality = validAudioQualities.includes(quality) ? quality : '192K'; // Default to 192K

    try {
        // Search YouTube for the song
        const searchResults = await yts(`${songName} official audio`);
        const video = searchResults.videos[0];

        if (!video) {
            return res.status(404).json({ error: 'No videos found for this song.' });
        }

        const videoUrl = video.url;
        const videoTitle = video.title.replace(/[^a-zA-Z0-9]/g, '_');

        // Validate video duration (max 2 hours)
        if (video.seconds > 7200) {
            return res.status(400).json({ error: 'This video is too long (max 2 hours).' });
        }

        // Create a temp directory for the file
        const tempDir = path.join(__dirname, 'temp');
        if (!fs.existsSync(tempDir)) {
            fs.mkdirSync(tempDir);
        }
        const outputFile = path.join(tempDir, `${videoTitle}_${audioQuality}.mp3`);
        const cookiesFile = path.join(__dirname, 'cookies.txt');

        // Use yt-dlp to download audio with cookies and specified quality
        const ytDlpCommand = `yt-dlp -x --audio-format mp3 --audio-quality ${audioQuality} --cookies "${cookiesFile}" -o "${outputFile}" "${videoUrl}"`;
        console.log(`[Audio] Running yt-dlp command: ${ytDlpCommand}`);
        const { stdout, stderr } = await execPromise(ytDlpCommand);
        console.log(`[Audio] yt-dlp stdout: ${stdout}`);
        console.log(`[Audio] yt-dlp stderr: ${stderr}`);

        // Check if the file exists
        if (!fs.existsSync(outputFile)) {
            console.error('[Audio] Output file not found after yt-dlp command.');
            return res.status(500).json({ error: 'Failed to download the audio.' });
        }

        // Set headers and send the file
        res.setHeader('Content-Disposition', `attachment; filename="${videoTitle}_${audioQuality}.mp3"`);
        res.setHeader('Content-Type', 'audio/mpeg');
        const fileStream = fs.createReadStream(outputFile);
        fileStream.pipe(res);

        // Clean up the temp file after sending
        fileStream.on('end', () => {
            fs.unlinkSync(outputFile);
        });

    } catch (error) {
        console.error('[Audio] Error in /download/audio:', error);
        res.status(500).json({ error: 'Failed to search or download the audio.' });
    }
});

// Download video endpoint
app.get('/download/video', async (req, res) => {
    const songName = req.query.song;
    const quality = req.query.quality;

    if (!songName || typeof songName !== 'string' || songName.trim() === '') {
        return res.status(400).json({ error: 'Please provide a song name.' });
    }

    // Validate quality parameter
    const validVideoQualities = ['144p', '240p', '360p', '480p', '720p', '1080p'];
    const videoQuality = validVideoQualities.includes(quality) ? quality : '720p'; // Default to 720p
    const qualityHeight = videoQuality.replace('p', ''); // e.g., "1080p" -> "1080"

    try {
        // Search YouTube for the video
        console.log(`[Video] Searching for song: ${songName}`);
        const searchResults = await yts(songName);
        const video = searchResults.videos[0];

        if (!video) {
            console.error('[Video] No videos found for the search query.');
            return res.status(404).json({ error: 'No videos found for this song.' });
        }

        const videoUrl = video.url;
        const videoTitle = video.title.replace(/[^a-zA-Z0-9]/g, '_');
        console.log(`[Video] Found video: ${video.title} (${videoUrl})`);

        // Validate video duration (max 2 hours)
        if (video.seconds > 7200) {
            console.error(`[Video] Video duration (${video.seconds} seconds) exceeds the 2-hour limit.`);
            return res.status(400).json({ error: 'This video is too long (max 2 hours).' });
        }

        // Create a temp directory for the file
        const tempDir = path.join(__dirname, 'temp');
        if (!fs.existsSync(tempDir)) {
            fs.mkdirSync(tempDir);
        }
        const outputFile = path.join(tempDir, `${videoTitle}_${videoQuality}.mp4`);
        const cookiesFile = path.join(__dirname, 'cookies.txt');

        // Use yt-dlp to download video with cookies and specified quality
        const ytDlpCommand = `yt-dlp -f "best[height<=${qualityHeight}]" --cookies "${cookiesFile}" -o "${outputFile}" "${videoUrl}"`;
        console.log(`[Video] Running yt-dlp command: ${ytDlpCommand}`);
        let stdout, stderr;
        try {
            const result = await execPromise(ytDlpCommand);
            stdout = result.stdout;
            stderr = result.stderr;
        } catch (err) {
            console.error('[Video] yt-dlp command failed:', err);
            console.error('[Video] yt-dlp stdout:', err.stdout || 'No stdout');
            console.error('[Video] yt-dlp stderr:', err.stderr || 'No stderr');
            throw err;
        }
        console.log(`[Video] yt-dlp stdout: ${stdout}`);
        console.log(`[Video] yt-dlp stderr: ${stderr}`);

        // Check if the file exists
        if (!fs.existsSync(outputFile)) {
            console.error('[Video] Output file not found after yt-dlp command.');
            return res.status(500).json({ error: 'Failed to download the video.' });
        }

        // Log file size for debugging
        const fileStats = fs.statSync(outputFile);
        console.log(`[Video] Downloaded file size: ${fileStats.size} bytes`);

        // Set headers and send the file
        res.setHeader('Content-Disposition', `attachment; filename="${videoTitle}_${videoQuality}.mp4"`);
        res.setHeader('Content-Type', 'video/mp4');
        const fileStream = fs.createReadStream(outputFile);
        fileStream.pipe(res);

        // Clean up the temp file after sending
        fileStream.on('end', () => {
            console.log('[Video] File sent successfully, cleaning up.');
            fs.unlinkSync(outputFile);
        });

        fileStream.on('error', (err) => {
            console.error('[Video] Error streaming file to client:', err);
        });

    } catch (error) {
        console.error('[Video] Error in /download/video:', error);
        res.status(500).json({ error: 'Failed to search or download the video.' });
    }
});

app.listen(port, () => {
    console.log(`Server running on port ${port}, ready to rip audio and video.`);
});
