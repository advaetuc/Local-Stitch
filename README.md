# Sequence-to-GIF Compiler

Compile an ordered folder of still images into an animated GIF.

## Use

1. Install Python 3.10 or newer.
2. Install the required packages with `pip install -r requirements.txt`.
3. Start the app with `python gif_compiler.py`.
4. Choose an image directory, set FPS and compression, and optionally enter a maximum width.
5. Select the GIF destination in Save As and choose **RENDER & EXPORT GIF**. Use **Cancel** to stop a render.

## Known limitations

Transparency becomes the white background; 16-bit grayscale PNGs may look washed out; animated inputs use their first frame; GIF is limited to 256 colors per frame by format.

## Build with PyInstaller

```text
pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --onefile --windowed --collect-all customtkinter --name GifCompiler gif_compiler.py
```

`--collect-all customtkinter` includes the theme and asset files needed by the frozen app. Build on each target OS; PyInstaller cannot cross-compile. On macOS, use `--onedir --windowed` instead of `--onefile`. Windows one-file executables can start more slowly and may trigger antivirus warnings; use `--onedir` to avoid those behaviors. Build with Python from python.org to use a current Tk version.
