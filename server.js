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
    max: 100, // Limit each IP to 100 requests per window
    message: 'Too many requests, slow the fuck down, asshole.',
});
app.use('/download', limiter);

app.use(express.urlencoded({ extended: true }));
app.set('trust proxy', 1); // Trust Heroku's proxy to fix the goddamn rate limiter

app.get('/', (req, res) => {
    res.send('YouTube Downloader API. Use /download/audio?song=<song_name>&cookies=<your_cookies> to rip audio or /download/video?song=<song_name>&cookies=<your_cookies> to rip video, you sneaky fuck.');
});

// Download audio endpoint
app.get('/download/audio', async (req, res) => {
    const songName = req.query.song;
    let cookies = req.query.cookies;

    if (!songName || typeof songName !== 'string' || songName.trim() === '') {
        return res.status(400).json({ error: 'Give me a fucking song name, you lazy bastard.' });
    }

    if (!cookies) {
        return res.status(400).json({ error: 'You need to pass cookies to bypass YouTube\'s bot detection, dumbass.' });
    }

    try {
        // Search YouTube for the song
        const searchResults = await yts(`${songName} official audio`);
        const video = searchResults.videos[0];

        if (!video) {
            return res.status(404).json({ error: 'No fucking videos found for this song, shithead.' });
        }

        const videoUrl = video.url;
        const videoTitle = video.title.replace(/[^a-zA-Z0-9]/g, '_');

        // Validate video duration (max 10 minutes)
        if (video.seconds > 600) {
            return res.status(400).json({ error: 'This video is too fucking long (max 10 minutes), asshole.' });
        }

        // Create a temp directory for the file
        const tempDir = path.join(__dirname, 'temp');
        if (!fs.existsSync(tempDir)) {
            fs.mkdirSync(tempDir);
        }
        const outputFile = path.join(tempDir, `${videoTitle}.mp3`);
        const cookiesFile = path.join(tempDir, 'cookies.txt');

        // Decode URL-encoded cookies and write to a temp file
        cookies = decodeURIComponent(cookies);
        fs.writeFileSync(cookiesFile, cookies);

        // Use yt-dlp to download audio with cookies
        const ytDlpCommand = `yt-dlp -x --audio-format mp3 --audio-quality 192K --cookies "${cookiesFile}" -o "${outputFile}" "${videoUrl}"`;
        await execPromise(ytDlpCommand);

        // Clean up cookies file
        if (fs.existsSync(cookiesFile)) {
            fs.unlinkSync(cookiesFile);
        }

        // Check if the file exists
        if (!fs.existsSync(outputFile)) {
            return res.status(500).json({ error: 'Failed to download the fucking audio, shit went wrong.' });
        }

        // Set headers and send the file
        res.setHeader('Content-Disposition', `attachment; filename="${videoTitle}.mp3"`);
        res.setHeader('Content-Type', 'audio/mpeg');
        const fileStream = fs.createReadStream(outputFile);
        fileStream.pipe(res);

        // Clean up the temp file after sending
        fileStream.on('end', () => {
            fs.unlinkSync(outputFile);
        });

    } catch (error) {
        console.error('Error:', error);
        res.status(500).json({ error: 'Failed to search or download the audio, shit hit the fan.' });
    }
});

// Download video endpoint
app.get('/download/video', async (req, res) => {
    const songName = req.query.song;
    let cookies = req.query.cookies;

    if (!songName || typeof songName !== 'string' || songName.trim() === '') {
        return res.status(400).json({ error: 'Give me a fucking song name, you lazy bastard.' });
    }

    if (!cookies) {
        return res.status(400).json({ error: 'You need to pass cookies to bypass YouTube\'s bot detection, dumbass.' });
    }

    try {
        // Search YouTube for the video
        const searchResults = await yts(songName);
        const video = searchResults.videos[0];

        if (!video) {
            return res.status(404).json({ error: 'No fucking videos found for this song, shithead.' });
        }

        const videoUrl = video.url;
        const videoTitle = video.title.replace(/[^a-zA-Z0-9]/g, '_');

        // Validate video duration (max 10 minutes)
        if (video.seconds > 600) {
            return res.status(400).json({ error: 'This video is too fucking long (max 10 minutes), asshole.' });
        }

        // Create a temp directory for the file
        const tempDir = path.join(__dirname, 'temp');
        if (!fs.existsSync(tempDir)) {
            fs.mkdirSync(tempDir);
        }
        const outputFile = path.join(tempDir, `${videoTitle}.mp4`);
        const cookiesFile = path.join(tempDir, 'cookies.txt');

        // Decode URL-encoded cookies and write to a temp file
        cookies = decodeURIComponent(cookies);
        fs.writeFileSync(cookiesFile, cookies);

        // Use yt-dlp to download video with cookies
        const ytDlpCommand = `yt-dlp -f "bestvideo+bestaudio/best" --cookies "${cookiesFile}" -o "${outputFile}" "${videoUrl}"`;
        await execPromise(ytDlpCommand);

        // Clean up cookies file
        if (fs.existsSync(cookiesFile)) {
            fs.unlinkSync(cookiesFile);
        }

        // Check if the file exists
        if (!fs.existsSync(outputFile)) {
            return res.status(500).json({ error: 'Failed to download the fucking video, shit went wrong.' });
        }

        // Set headers and send the file
        res.setHeader('Content-Disposition', `attachment; filename="${videoTitle}.mp4"`);
        res.setHeader('Content-Type', 'video/mp4');
        const fileStream = fs.createReadStream(outputFile);
        fileStream.pipe(res);

        // Clean up the temp file after sending
        fileStream.on('end', () => {
            fs.unlinkSync(outputFile);
        });

    } catch (error) {
        console.error('Error:', error);
        res.status(500).json({ error: 'Failed to search or download the video, shit hit the fan.' });
    }
});

app.listen(port, () => {
    console.log(`Server running on port ${port}, ready to rip some fucking audio and video.`);
});
