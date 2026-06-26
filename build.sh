#!/usr/bin/env bash
# ბიბლიოთეკების ინსტალაცია გლობალურად
pip install -r requirements.txt --user

# დარწმუნება, რომ Gunicorn-ის ბილიკი სისტემისთვის ხილვადია
export PATH=$PATH:$HOME/.local/bin

# FFmpeg-ის გადმოწერა
mkdir -p ffmpeg
curl -L https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz | tar -xJ --strip-components=1 -C ffmpeg
