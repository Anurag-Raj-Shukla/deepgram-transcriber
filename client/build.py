import PyInstaller.__main__
import os
import sys

base = os.path.dirname(os.path.abspath(__file__))

PyInstaller.__main__.run([
    os.path.join(base, "client.py"),
    '--onefile',
    '--windowed',
    '--name', 'Transcriber',
    '--add-data', f'{os.path.join(base, "config.json")};.',
    '--clean'
])