# APK Texdecoder

You may've noticed that a lot of old Android games have `.dds*` files and no image files in their assets. 
These DDS files are compressed textures that are used directly by the GPU to render, but it's hard to preview them.

This script lets you extract them from the APK and convert to the following formats:
- PNG
- ETC1
- ATC (no alpha)
- ATCI (ATC but with alpha)
- PVR (decode-only)

## Installation

You need apktool to extract the APK, and CompressonatorCLI to convert PNG to ETC1/ATC/ATCI.
Install apktool from [here](https://github.com/iBotPeaches/Apktool).
Download [compressonatorcli](https://github.com/GPUOpen-Tools/compressonator/releases) for your platform, extract it and place the `compressonatorcli` folder in the same directory as this script.  
Set up venv and do `pip install -r requirements.txt` to install dependencies.

Run `python3 main.py` to get further instructions; it accepts `etc1`, `atc`, and `atci` as cli arguments to enable conversions. 
PNG conversion is always on.

Tested on Debian with apktool installed as a system package.

### I am not responsible for any misuse of this script or converted assets.

Remember that extracted and converted assets still belong to the original APK owner, and you should not use them for
anything other than personal use unless specified otherwise by the license of the original APK.
