# Use a base image with Node.js and Debian
FROM node:18-bullseye

# Install Python, pip, and FFmpeg
RUN apt-get update && apt-get install -y python3 python3-pip ffmpeg && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy package.json and install Node.js dependencies
COPY package.json .
RUN npm install

# Copy requirements.txt and install Python dependencies
COPY requirements.txt .
RUN pip3 install -r requirements.txt

# Copy the rest of the application files
COPY . .

# Expose the port
EXPOSE 3000

# Run the app
CMD ["node", "server.js"]
