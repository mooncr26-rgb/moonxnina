#!/usr/bin/env bash
# შეცდომის შემთხვევაში პროცესის გაჩერება
set -o errexit

# ბიბლიოთეკების ინსტალაცია
pip install -r requirements.txt

# FFmpeg static ბინარების ჩამოტვირთვა და მომზადება
mkdir -p ffmpeg
curl -L https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz | tar -xJ --strip-components=1 -C ffmpeg