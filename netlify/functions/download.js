const { exec } = require('child_process');
const { promisify } = require('util');
const fs = require('fs');
const path = require('path');

const execPromise = promisify(exec);

const isValidYouTubeUrl = (url) => {
    return /^https?:\/\/(www\.)?(youtube\.com|youtu\.be)\/(watch\?v=|shorts\/|embed\/)?[A-Za-z0-9_-]{11}(\?.*)?$/.test(url);
};

exports.handler = async (event, context) => {
    const { path: endpoint, queryStringParameters } = event;
    const { song, quality, cb } = queryStringParameters || {};
    const cacheBuster = cb || Date.now();
    const tempDir = '/tmp'; // Use the writable /tmp directory
    const ytDlpPath = '/opt/buildhome/python3/bin/yt-dlp'; // Adjust based on build environment

    // Create a temporary cookies file from environment variable
    const cookiesContent = process.env.YOUTUBE_COOKIES;
    if (!cookiesContent) {
        return {
            statusCode: 500,
            body: JSON.stringify({ error: 'YouTube cookies not set in environment variables.' }),
        };
    }
    const cookiesFile = path.join(tempDir, 'temp_cookies.txt');
    if (!fs.existsSync(tempDir)) {
        fs.mkdirSync(tempDir, { recursive: true }); // Should already exist, but just in case
    }
    fs.writeFileSync(cookiesFile, cookiesContent);

    if (!song || !isValidYouTubeUrl(song)) {
        fs.unlinkSync(cookiesFile); // Clean up
        return {
            statusCode: 400,
            body: JSON.stringify({ error: 'Please provide a valid YouTube URL.' }),
        };
    }

    const userAgent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0';

    try {
        let outputFile = null; // Initialize to null
        let videoInfo, videoTitle, durationSeconds;

        // Fetch metadata
        const metadataCommand = `${ytDlpPath} --dump-json --cookies "${cookiesFile}" --user-agent "${userAgent}" "${song}"`;
        const { stdout: metadataStdout } = await execPromise(metadataCommand);
        videoInfo = JSON.parse(metadataStdout);
        videoTitle = videoInfo.title.replace(/[^a-zA-Z0-9]/g, '_');
        durationSeconds = videoInfo.duration;

        if (durationSeconds > 7200) {
            fs.unlinkSync(cookiesFile); // Clean up
            return {
                statusCode: 400,
                body: JSON.stringify({ error: 'This video is too long (max 2 hours).' }),
            };
        }

        if (endpoint === '/download/audio') {
            const validAudioQualities = ['128K', '192K', '320K'];
            const audioQuality = validAudioQualities.includes(quality) ? quality : '192K';
            outputFile = path.join(tempDir, `${videoTitle}_${audioQuality}_${cacheBuster}.mp3`);

            const ytDlpCommand = `${ytDlpPath} -x --audio-format mp3 --audio-quality ${audioQuality} --cookies "${cookiesFile}" --user-agent "${userAgent}" -o "${outputFile}" "${song}"`;
            await execPromise(ytDlpCommand);

            if (!fs.existsSync(outputFile)) {
                throw new Error('Failed to download the audio.');
            }

            const fileStream = fs.readFileSync(outputFile);
            fs.unlinkSync(outputFile);
            fs.unlinkSync(cookiesFile); // Clean up

            return {
                statusCode: 200,
                headers: {
                    'Content-Disposition': `attachment; filename="${videoTitle}_${audioQuality}.mp3"`,
                    'Content-Type': 'audio/mpeg',
                },
                body: fileStream.toString('base64'),
                isBase64Encoded: true,
            };
        } else if (endpoint === '/download/video') {
            const validVideoQualities = ['144p', '240p', '360p', '480p', '720p', '1080p'];
            const videoQuality = validVideoQualities.includes(quality) ? quality : '1080p';
            const qualityFormatMap = {
                '144p': ['160+251', '133+251', '134+251'],
                '240p': ['133+251', '134+251', '135+251'],
                '360p': ['18', '134+251', '135+251', '136+251'],
                '480p': ['135+251', '136+251', '137+251'],
                '720p': ['136+251', '137+251', '135+251'],
                '1080p': ['137+251', '136+251', '135+251'],
            };
            let formatCodes = qualityFormatMap[videoQuality] || ['137+251', '136+251', '135+251'];

            outputFile = path.join(tempDir, `${videoTitle}_${videoQuality}_${cacheBuster}.mp4`);

            let formatWorked = false;
            for (const formatCode of formatCodes) {
                try {
                    const ytDlpCommand = `${ytDlpPath} --user-agent "${userAgent}" -f "${formatCode}" --merge-output-format mp4 --cookies "${cookiesFile}" -o "${outputFile}" "${song}"`;
                    await execPromise(ytDlpCommand);

                    if (fs.existsSync(outputFile)) {
                        formatWorked = true;
                        break;
                    }
                } catch (err) {
                    fs.unlinkSync(outputFile).catch(() => {});
                }
            }

            if (!formatWorked) {
                fs.unlinkSync(cookiesFile); // Clean up
                throw new Error('Failed to download the video with any format.');
            }

            const fileStream = fs.readFileSync(outputFile);
            fs.unlinkSync(outputFile);
            fs.unlinkSync(cookiesFile); // Clean up

            return {
                statusCode: 200,
                headers: {
                    'Content-Disposition': `attachment; filename="${videoTitle}_${videoQuality}.mp4"`,
                    'Content-Type': 'video/mp4',
                },
                body: fileStream.toString('base64'),
                isBase64Encoded: true,
            };
        } else {
            fs.unlinkSync(cookiesFile); // Clean up
            return {
                statusCode: 404,
                body: JSON.stringify({ error: 'Endpoint not found.' }),
            };
        }
    } catch (error) {
        if (outputFile && fs.existsSync(outputFile)) {
            fs.unlinkSync(outputFile);
        }
        fs.unlinkSync(cookiesFile); // Clean up
        return {
            statusCode: 500,
            body: JSON.stringify({ error: 'Download failed.', details: error.message }),
        };
    }
};
