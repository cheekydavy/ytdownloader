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

// Install Python dependencies dynamically
const installDependencies = async () => {
    try {
        console.log('[Startup] Ensuring Python, pip, and venv are available...');
        const { stdout: pythonCheck } = await execPromise('python3 --version');
        console.log(`[Startup] Python version: ${pythonCheck.trim()}`);
        const { stdout: pipCheck } = await execPromise('pip3 --version');
        console.log(`[Startup] pip version: ${pipCheck.trim()}`);

        // Create a virtual environment
        const venvPath = path.join(__dirname, 'venv');
        console.log('[Startup] Creating virtual environment...');
        await execPromise(`python3 -m venv ${venvPath}`);
        console.log(`[Startup] Virtual environment created at: ${venvPath}`);

        // Install requirements.txt using the virtual env
        const pipInstallCmd = `${venvPath}/bin/pip install -r ${path.join(__dirname, 'requirements.txt')}`;
        console.log(`[Startup] Installing Python dependencies: ${pipInstallCmd}`);
        const { stdout: pipInstallOut, stderr: pipInstallErr } = await execPromise(pipInstallCmd);
        console.log(`[Startup] pip install output: ${pipInstallOut}`);
        if (pipInstallErr) console.warn(`[Startup] pip install stderr: ${pipInstallErr}`);

        // Verify yt-dlp
        const ytDlpCmd = `${venvPath}/bin/yt-dlp --version`;
        const { stdout: ytDlpCheck } = await execPromise(ytDlpCmd);
        console.log(`[Startup] yt-dlp version: ${ytDlpCheck.trim()}`);

        // Verify ffmpeg
        const { stdout: ffmpegCheck } = await execPromise('ffmpeg -version');
        console.log(`[Startup] ffmpeg version: ${ffmpegCheck.split('\n')[0]}`);
    } catch (err) {
        console.error('[Startup] Failed to install dependencies: ' + err.message);
        console.error('[Startup] Error details: ' + err.stack);
        throw new Error('Dependency installation failed');
    }
};

// Validate YouTube URL
const isValidYouTubeUrl = (url) => {
    return /^https?:\/\/(www\.)?(youtube\.com|youtu\.be)\/(watch\?v=|shorts\/|embed\/)?[A-Za-z0-9_-]{11}(\?.*)?$/.test(url);
};

// Download audio endpoint (unchanged)
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

    let outputFile = null;
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
        const venvPath = path.join(__dirname, 'venv');
        const metadataCommand = `${venvPath}/bin/yt-dlp --dump-json --cookies "${cookiesFile}" "${songUrl}"`;
        console.log(`[Audio] Fetching metadata for URL: ${songUrl}, cacheBuster: ${cacheBuster}`);
        console.log(`[Audio] Running command: ${metadataCommand}`);
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
        outputFile = path.join(tempDir, `${videoTitle}_${audioQuality}_${cacheBuster}.mp3`);

        // Use yt-dlp to download audio with cookies and specified quality
        const ytDlpCommand = `${venvPath}/bin/yt-dlp -x --audio-format mp3 --audio-quality ${audioQuality} --cookies "${cookiesFile}" -o "${outputFile}" "${songUrl}"`;
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

        fileStream.on('error', (err) => {
            console.error('[Audio] Error streaming file to client: ' + err.message);
        });

    } catch (error) {
        console.error('[Audio] Error in /download/audio: ' + error.message + ', Stack: ' + error.stack);
        if (outputFile && fs.existsSync(outputFile)) {
            fs.unlinkSync(outputFile);
            console.log(`[Audio] Cleaned up temp file on error: ${outputFile}`);
        }
        res.status(500).json({ error: 'Failed to download the audio.', details: error.message });
    }
});

// Download video endpoint (updated)
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
    const videoQuality = validVideoQualities.includes(quality) ? quality : '1080p';

    // Map quality to yt-dlp format codes with combined formats and fallbacks
    const qualityFormatMap = {
        '144p': ['160+251', '133+251', '134+251'], // 144p video + best audio
        '240p': ['133+251', '134+251', '135+251'], // 240p video + best audio
        '360p': ['18', '134+251', '135+251', '136+251'], // Prefer format 18 (combined), then merge
        '480p': ['135+251', '136+251', '137+251'],
        '720p': ['136+251', '137+251', '135+251'],
        '1080p': ['137+251', '136+251', '135+251'],
    };
    let formatCodes = qualityFormatMap[videoQuality] || ['137+251', '136+251', '135+251'];

    let outputFile = null;
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
        let videoInfo;
        try {
            const venvPath = path.join(__dirname, 'venv');
            const metadataCommand = `${venvPath}/bin/yt-dlp --dump-json --cookies "${cookiesFile}" "${songUrl}"`;
            console.log(`[Video] Fetching metadata for URL: ${songUrl}, cacheBuster: ${cacheBuster}`);
            console.log(`[Video] Running command: ${metadataCommand}`);
            const { stdout: metadataStdout, stderr: metadataStderr } = await execPromise(metadataCommand);
            if (metadataStderr) {
                console.error(`[Video] Metadata fetch stderr: ${metadataStderr}`);
            }
            videoInfo = JSON.parse(metadataStdout);
        } catch (err) {
            console.error(`[Video] Failed to fetch metadata: ${err.message}`);
            throw new Error('Unable to fetch video metadata');
        }

        const videoTitle = videoInfo.title.replace(/[^a-zA-Z0-9]/g, '_');
        const durationSeconds = videoInfo.duration;

        console.log(`[Video] Video title: ${videoInfo.title}, duration: ${durationSeconds}s, requested quality: ${videoQuality}`);

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
        outputFile = path.join(tempDir, `${videoTitle}_${videoQuality}_${cacheBuster}.mp4`);

        // Check available formats to ensure the requested quality is available
        let availableFormats;
        try {
            const venvPath = path.join(__dirname, 'venv');
            const formatsCommand = `${venvPath}/bin/yt-dlp --list-formats --cookies "${cookiesFile}" "${songUrl}"`;
            console.log(`[Video] Fetching available formats: ${formatsCommand}`);
            const { stdout: formatsStdout, stderr: formatsStderr } = await execPromise(formatsCommand);
            if (formatsStderr) {
                console.error(`[Video] Formats fetch stderr: ${formatsStderr}`);
            }
            console.log(`[Video] Available formats: ${formatsStdout}`);
            availableFormats = formatsStdout;
        } catch (err) {
            console.error(`[Video] Failed to fetch formats: ${err.message}`);
            throw new Error('Unable to fetch available formats');
        }

        // Adjust format codes based on availability
        const requestedFormats = formatCodes;
        formatCodes = [];
        for (const formatCode of requestedFormats) {
            const [videoFormat] = formatCode.split('+'); // Split video+audio formats
            if (availableFormats.includes(videoFormat)) {
                formatCodes.push(formatCode);
            }
        }

        // If no requested formats are available, fall back to a safe default
        if (formatCodes.length === 0) {
            console.warn(`[Video] Requested formats ${requestedFormats.join(', ')} not available. Falling back to default.`);
            formatCodes = ['bestvideo[height<=720]+bestaudio/best', 'bestvideo[height<=480]+bestaudio/best', 'best'];
        }

        console.log(`[Video] Using format codes: ${formatCodes.join(', ')}`);

        // Spoof user-agent to bypass potential YouTube restrictions
        const userAgent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36';

        // Try each format code until one works
        let stdout, stderr;
        let formatWorked = false;
        let usedFormatCode = null;
        for (const formatCode of formatCodes) {
            try {
                const venvPath = path.join(__dirname, 'venv');
                const ytDlpCommand = `${venvPath}/bin/yt-dlp --user-agent "${userAgent}" -f "${formatCode}" --merge-output-format mp4 --cookies "${cookiesFile}" -o "${outputFile}" "${songUrl}"`;
                console.log(`[Video] Running yt-dlp command with format ${formatCode}: ${ytDlpCommand}`);
                const result = await execPromise(ytDlpCommand);
                stdout = result.stdout;
                stderr = result.stderr;
                console.log(`[Video] yt-dlp stdout: ${stdout}`);
                console.log(`[Video] yt-dlp stderr: ${stderr}`);

                // Check if the file exists and has a reasonable size
                if (!fs.existsSync(outputFile)) {
                    console.error(`[Video] Output file not found after yt-dlp command with format ${formatCode}.`);
                    continue;
                }

                const fileStats = fs.statSync(outputFile);
                const fileSize = fileStats.size;
                console.log(`[Video] Downloaded file size with format ${formatCode}: ${fileSize} bytes`);

                // Rough duration check
                const roughBitrate = 1000000; // 1 Mbps for video + audio
                const estimatedDuration = Math.floor((fileSize * 8) / roughBitrate);
                console.log(`[Video] Estimated duration with format ${formatCode}: ${estimatedDuration}s (expected: ${durationSeconds}s)`);
                const durationTolerance = 30;
                if (Math.abs(durationSeconds - estimatedDuration) > durationTolerance) {
                    console.error(`[Video] Duration mismatch with format ${formatCode}, trying next format.`);
                    if (fs.existsSync(outputFile)) {
                        fs.unlinkSync(outputFile);
                    }
                    continue;
                }

                formatWorked = true;
                usedFormatCode = formatCode;
                break;
            } catch (err) {
                console.error(`[Video] yt-dlp command failed with format ${formatCode}: ${err.message}`);
                console.error(`[Video] yt-dlp stdout: ${err.stdout || 'No stdout'}`);
                console.error(`[Video] yt-dlp stderr: ${err.stderr || 'No stderr'}`);
                if (fs.existsSync(outputFile)) {
                    fs.unlinkSync(outputFile);
                }
            }
        }

        if (!formatWorked) {
            console.error('[Video] All format codes failed.');
            return res.status(500).json({
                error: 'Failed to download the video with any format.',
                details: `All formats (${requestedFormats.join(', ')}) failed. Available formats: ${availableFormats}`,
            });
        }

        console.log(`[Video] Successfully downloaded with format ${usedFormatCode}`);

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
            console.error('[Video] Error streaming file to client: ' + err.message);
            if (fs.existsSync(outputFile)) {
                fs.unlinkSync(outputFile);
                console.log(`[Video] Cleaned up temp file on stream error: ${outputFile}`);
            }
            if (!res.headersSent) {
                res.status(500).json({ error: 'Failed to stream the video.', details: err.message });
            }
        });

    } catch (error) {
        console.error('[Video] Error in /download/video: ' + error.message + ', Stack: ' + error.stack);
        if (outputFile && fs.existsSync(outputFile)) {
            fs.unlinkSync(outputFile);
            console.log(`[Video] Cleaned up temp file on error: ${outputFile}`);
        }
        res.status(500).json({ error: 'Failed to download the video.', details: error.message });
    }
});

// Debug endpoint to check dependencies
app.get('/debug', async (req, res) => {
    try {
        const venvPath = path.join(__dirname, 'venv');
        const { stdout: ytDlpPath } = await execPromise(`which ${venvPath}/bin/yt-dlp`);
        const { stdout: ytDlpVer } = await execPromise(`${venvPath}/bin/yt-dlp --version`);
        const { stdout: ffmpegPath } = await execPromise('which ffmpeg');
        const { stdout: ffmpegVer } = await execPromise('ffmpeg -version');
        const { stdout: pythonVer } = await execPromise('python3 --version');
        res.json({
            ytDlpPath: ytDlpPath.trim(),
            ytDlpVersion: ytDlpVer.trim(),
            ffmpegPath: ffmpegPath.trim(),
            ffmpegVersion: ffmpegVer.split('\n')[0],
            pythonVersion: pythonVer.trim()
        });
    } catch (err) {
        res.status(500).json({ error: 'Debug failed', details: err.message });
    }
});

// Install dependencies and start server
installDependencies().then(() => {
    app.listen(port, () => {
        console.log(`Server running on port ${port}, ready to rip audio and video.`);
    });
}).catch((err) => {
    console.error('Startup failed: ' + err.message);
    process.exit(1);
});
