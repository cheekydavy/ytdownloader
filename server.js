const express = require('express');
const ytdl = require('ytdl-core');
const fs = require('fs');
const path = require('path');
const { exec } = require('child_process');
const ffmpeg = require('ffmpeg-static');
const yts = require('yt-search');

const app = express();
const port = process.env.PORT || 3000; // Heroku sets PORT env variable

// Middleware to parse URL-encoded data
app.use(express.urlencoded({ extended: true }));

// Root endpoint for basic info
app.get('/', (req, res) => {
    res.send('YouTube Audio Downloader API. Use /download?song=<song_name> to download audio.');
});

// Download endpoint
app.get('/download', async (req, res) => {
    const songName = req.query.song;

    // Validate the song name
    if (!songName || typeof songName !== 'string' || songName.trim() === '') {
        return res.status(400).json({ error: 'Please provide a valid song name.' });
    }

    try {
        // Search YouTube for the song
        const searchResults = await yts(songName);
        const video = searchResults.videos[0]; // Get the top result

        if (!video) {
            return res.status(404).json({ error: 'No videos found for this song.' });
        }

        const videoUrl = video.url; // e.g., https://www.youtube.com/watch?v=dQw4w9WgXcQ
        const videoTitle = video.title.replace(/[^a-zA-Z0-9]/g, '_'); // Sanitize filename
        const tempFile = path.join(__dirname, `${videoTitle}_temp.mp4`);
        const outputFile = path.join(__dirname, `${videoTitle}.mp3`);

        // Download audio stream
        const audioStream = ytdl(videoUrl, { quality: 'highestaudio', filter: 'audioonly' });
        const fileStream = fs.createWriteStream(tempFile);
        audioStream.pipe(fileStream);

        // Wait for the download to finish
        await new Promise((resolve, reject) => {
            fileStream.on('finish', resolve);
            fileStream.on('error', reject);
        });

        // Convert to MP3 using FFmpeg
        await new Promise((resolve, reject) => {
            const command = `"${ffmpeg}" -i "${tempFile}" -vn -ar 44100 -ac 2 -b:a 192k "${outputFile}"`;
            exec(command, (err) => {
                if (err) return reject(err);
                resolve();
            });
        });

        // Set headers for file download
        res.setHeader('Content-Disposition', `attachment; filename="${videoTitle}.mp3"`);
        res.setHeader('Content-Type', 'audio/mpeg');

        // Stream the MP3 file to the client
        const readStream = fs.createReadStream(outputFile);
        readStream.pipe(res);

        // Clean up temporary files after streaming
        readStream.on('end', () => {
            fs.unlinkSync(tempFile); // Delete the temp audio file
            fs.unlinkSync(outputFile); // Delete the MP3 file
        });

        readStream.on('error', (err) => {
            console.error('Error streaming file:', err);
            res.status(500).json({ error: 'Error streaming the audio file.' });
            // Clean up in case of error
            if (fs.existsSync(tempFile)) fs.unlinkSync(tempFile);
            if (fs.existsSync(outputFile)) fs.unlinkSync(outputFile);
        });
    } catch (error) {
        console.error('Error:', error);
        res.status(500).json({ error: 'Failed to search, download, or convert the audio.' });
        // Clean up in case of error
        const tempFile = path.join(__dirname, `${videoTitle}_temp.mp4`);
        const outputFile = path.join(__dirname, `${videoTitle}.mp3`);
        if (fs.existsSync(tempFile)) fs.unlinkSync(tempFile);
        if (fs.existsSync(outputFile)) fs.unlinkSync(outputFile);
    }
});

// Start the server
app.listen(port, () => {
    console.log(`Server running on port ${port}`);
});
