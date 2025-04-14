const express = require('express');
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
    res.send('YouTube Downloader API. Use /download/audio?song=<song_url>&quality=<quality> to rip audio or /download/video?song=<song_url>&quality=<quality> to rip video.');
});

// Validate YouTube URL
const isValidYouTubeUrl = (url) => {
    return /^https?:\/\/(www\.)?(youtube\.com|youtu\.be)\/(watch\?v=|shorts\/|embed\/)?[A-Za-z0-9_-]{11}(\?.*)?$/.test(url);
};

// Download audio endpoint
app.get('/download/audio', async (req, res) => {
    const songUrl = req.query.song;
    const quality = req.query.quality;
    const cacheBuster = req.query.cb || Date.now(); // For debugging cache issues

    if (!songUrl || typeof songUrl !== 'string' || !isValidYouTubeUrl(songUrl)) {
        console.error(`[Audio] Invalid or missing YouTube URL: ${songUrl}`);
        return res.status(400).json({ error: 'Please provide a valid YouTube URL.' });
    }

    // Validate quality parameter
    const validAudioQualities = ['128K', '192K', '320K'];
    const audioQuality = validAudioQualities.includes(quality) ? quality : '192K'; // Default to 192K

    try {
        // Check cookies file
        const cookiesFile = path.join(__dirname, 'cookies.txt');
        if (!fs.existsSync(cookiesFile)) {
            console.error(`[Audio] Cookies file not found at ${cookiesFile}`);
            return res.status(500).json({ error: 'Cookies file missing, can’t authenticate with YouTube.' });
        }
        const cookiesContent = fs.readFileSync(cookiesFile, 'utf8');
        console.log(`[Audio] Cookies file content: ${cookiesContent}`);

        // Fetch video metadata using yt-dlp --dump-json with cookies
        const metadataCommand = `yt-dlp --dump-json --cookies "${cookiesFile}" "${songUrl}"`;
        console.log(`[Audio] Fetching metadata for URL: ${songUrl}, cacheBuster: ${cacheBuster}`);
        const { stdout: metadataStdout, stderr: metadataStderr } = await execPromise(metadataCommand);
        if (metadataStderr) {
            console.error(`[Audio] Metadata fetch stderr: ${metadataStderr}`);
        }
        const videoInfo = JSON.parse(metadataStdout);

        const videoTitle = videoInfo.title.replace(/[^a-zA-Z0-9]/g, '_');
        const durationSeconds = videoInfo.duration;

        console.log(`[Audio] Video title: ${videoInfo.title}, duration: ${durationSeconds}s, quality: ${audioQuality}`);

        // Validate video duration (max 2 hours)
        if (durationSeconds > 7200) {
            console.error(`[Audio] Video duration (${durationSeconds} seconds) exceeds the 2-hour limit.`);
            return res.status(400).json({ error: 'This video is too long (max 2 hours).' });
        }

        // Create a temp directory for the file
        const tempDir = path.join(__dirname, 'temp');
        if (!fs.existsSync(tempDir)) {
            fs.mkdirSync(tempDir);
        }
        const outputFile = path.join(tempDir, `${videoTitle}_${audioQuality}_${cacheBuster}.mp3`);

        // Use yt-dlp to download audio with cookies and specified quality
        const ytDlpCommand = `yt-dlp -x --audio-format mp3 --audio-quality ${audioQuality} --cookies "${cookiesFile}" -o "${outputFile}" "${songUrl}"`;
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
            if (fs.existsSync(outputFile)) {
                fs.unlinkSync(outputFile);
                console.log(`[Audio] Cleaned up temp file: ${outputFile}`);
            }
        });

    } catch (error) {
        console.error('[Audio] Error in /download/audio:', error);
        res.status(500).json({ error: 'Failed to download the audio.' });
    }
});

// Download video endpoint
app.get('/download/video', async (req, res) => {
    const songUrl = req.query.song;
    const quality = req.query.quality;
    const cacheBuster = req.query.cb || Date.now();

    if (!songUrl || typeof songUrl !== 'string' || !isValidYouTubeUrl(songUrl)) {
        console.error(`[Video] Invalid or missing YouTube URL: ${songUrl}`);
        return res.status(400).json({ error: 'Please provide a valid YouTube URL.' });
    }

    // Validate quality parameter, prioritize user choice, default to 1080p
    const validVideoQualities = ['144p', '240p', '360p', '480p', '720p', '1080p'];
    const videoQuality = validVideoQualities.includes(quality) ? quality : '1080p'; // Default to 1080p
    // Map quality to yt-dlp format codes for precise selection
    const qualityFormatMap = {
        '144p': '160',  // 144p video + audio
        '240p': '133',  // 240p video + audio
        '360p': '134',  // 360p video + audio
        '480p': '135',  // 480p video + audio
        '720p': '136',  // 720p video + audio
        '1080p': '137', // 1080p video + audio
    };
    const formatCode = qualityFormatMap[videoQuality] || '137'; // Fallback to 1080p

    try {
        // Check cookies file
        const cookiesFile = path.join(__dirname, 'cookies.txt');
        if (!fs.existsSync(cookiesFile)) {
            console.error(`[Video] Cookies file not found at ${cookiesFile}`);
            return res.status(500).json({ error: 'Cookies file missing, can’t authenticate with YouTube.' });
        }
        const cookiesContent = fs.readFileSync(cookiesFile, 'utf8');
        console.log(`[Video] Cookies file content: ${cookiesContent}`);

        // Fetch video metadata using yt-dlp --dump-json with cookies
        const metadataCommand = `yt-dlp --dump-json --cookies "${cookiesFile}" "${songUrl}"`;
        console.log(`[Video] Fetching metadata for URL: ${songUrl}, cacheBuster: ${cacheBuster}`);
        const { stdout: metadataStdout, stderr: metadataStderr } = await execPromise(metadataCommand);
        if (metadataStderr) {
            console.error(`[Video] Metadata fetch stderr: ${metadataStderr}`);
        }
        const videoInfo = JSON.parse(metadataStdout);

        const videoTitle = videoInfo.title.replace(/[^a-zA-Z0-9]/g, '_');
        const durationSeconds = videoInfo.duration;

        console.log(`[Video] Video title: ${videoInfo.title}, duration: ${durationSeconds}s, quality: ${videoQuality}`);

        // Validate video duration (max 2 hours)
        if (durationSeconds > 7200) {
            console.error(`[Video] Video duration (${durationSeconds} seconds) exceeds the 2-hour limit.`);
            return res.status(400).json({ error: 'This video is too long (max 2 hours).' });
        }

        // Create a temp directory for the file
        const tempDir = path.join(__dirname, 'temp');
        if (!fs.existsSync(tempDir)) {
            fs.mkdirSync(tempDir);
        }
        const outputFile = path.join(tempDir, `${videoTitle}_${videoQuality}_${cacheBuster}.mp4`);

        // Use yt-dlp to download video with cookies and specified quality
        const ytDlpCommand = `yt-dlp -f "${formatCode}+bestaudio/best" --merge-output-format mp4 --cookies "${cookiesFile}" -o "${outputFile}" "${songUrl}"`;
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
            if (fs.existsSync(outputFile)) {
                fs.unlinkSync(outputFile);
                console.log(`[Video] Cleaned up temp file: ${outputFile}`);
            }
        });

        fileStream.on('error', (err) => {
            console.error('[Video] Error streaming file to client:', err);
        });

    } catch (error) {
        console.error('[Video] Error in /download/video:', error);
        res.status(500).json({ error: 'Failed to download the video.' });
    }
});

app.listen(port, () => {
    console.log(`Server running on port ${port}, ready to rip audio and video.`);
});
