Inspired by https://poetry.camera/ but totally rewrite from scratch.

Install Bullseye Raspberry Pi OS (not bookworm. which has no legacy camera setting)

sudo raspi-config
Interface setting -> Legacy Camera

sudo apt update
sudo apt install libjpeg-dev zlib1g-dev libtiff-dev libfreetype6-dev liblcms2-dev libwebp-dev tcl-dev tk-dev
sudo apt install python3.9-dev
sudo apt install python3-rpi.gpio
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
