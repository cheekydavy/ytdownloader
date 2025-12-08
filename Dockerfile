FROM python:3.12-slim-bullseye 

RUN apt-get update && apt-get install -y \
    ffmpeg \
    nodejs \
    npm \
 && rm -rf /var/lib/apt/lists/*

RUN pip install js2py pyduktape2 py-mini-racer

WORKDIR /app
COPY requirements.txt .
RUN pip3 install -r requirements.txt
COPY . .
EXPOSE 5000
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "360", "app:app"]
