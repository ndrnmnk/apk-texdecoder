import argparse
from pathlib import Path
import struct
import subprocess
import sys
from tempfile import TemporaryDirectory

from PIL import Image
import texture2ddecoder


COMPRESSONATOR = Path(__file__).resolve().parent / "compressonatorcli/compressonatorcli"

ENCODINGS = {
    "etc1": ("ETC_RGB", b"ETC ", b"ETC1", ".ddsetc1"),
    "atc": ("ATC_RGB", b"ATC ", b"ATC ", ".ddsatc"),
    "atci": ("ATC_RGBA_Interpolated", b"ATCI", b"ATCI", ".ddsatc"),
}

DDS_FORMATS = {
    b"ATC ": "ATC",
    b"ATCA": "ATC (explicit alpha)",
    b"ATCI": "ATCI",
    b"ETC ": "ETC1",
    b"ETC1": "ETC1",
}
ASSET_EXTENSIONS = {".ddsatc": "ATC", ".ddsetc1": "ETC1"}


def extract_assets(apk_path, output_dir):
    subprocess.run(
        [
            "apktool", "decode", "--no-src", "--no-res", "--output",
            str(output_dir.resolve()), str(apk_path.resolve()),
        ],
        check=True,
    )
    return output_dir / "assets"


def existing_texture_format(path):
    with path.open("rb") as source:
        header = source.read(128)
    if header.startswith(b"DDS "):
        return DDS_FORMATS.get(header[84:88])
    if header.startswith((b"PKM 10", b"PKM 20")):
        if len(header) >= 16 and header[6:8] == b"\x00\x00":
            return "ETC1"
        return None
    return ASSET_EXTENSIONS.get(path.suffix.lower())


def decode_dds_pvr(input_path: str, output_path: str):
    with open(input_path, "rb") as f:
        magic = f.read(4)
        if magic != b"DDS ":
            raise ValueError(f"Not a valid DDS file (Magic: {magic})")

        # Read DDS_HEADER (124 bytes)
        header_bytes = f.read(124)
        if len(header_bytes) < 124:
            raise ValueError("Incomplete DDS header")

        # DirectDraw Surface layout:
        # dwSize(4), dwFlags(4), dwHeight(4), dwWidth(4), dwPitchOrLinearSize(4), dwDepth(4), dwMipMapCount(4)...
        # Total offset to pixel data is 128 bytes (4 magic + 124 header)
        height, width = struct.unpack_from("<II", header_bytes, offset=8)

        # Pixel format starts at offset 72 of DDS_HEADER (76 bytes into file)
        # DDS_PIXELFORMAT: dwSize(4), dwFlags(4), dwFourCC(4)...
        fourcc = header_bytes[80:84].decode("ascii", errors="replace")

        print(f"Detected dimensions: {width}x{height}")
        print(f"FourCC: {fourcc}")

        if not width or not height:
            raise ValueError("Invalid DDS dimensions")

        # Determine 2bpp vs 4bpp
        # PVR4 / PVR2 are standard non-standard FourCCs used in mobile DDS containers
        is_2bpp = False
        if fourcc == "PVR2":
            is_2bpp = True
            expected_payload = (max(width, 16) * max(height, 8) * 2) // 8
        elif fourcc == "PVR4":
            is_2bpp = False
            expected_payload = (max(width, 8) * max(height, 8) * 4) // 8
        else:
            print(f"Warning: Expected FourCC 'PVR4' or 'PVR2', got '{fourcc}'. Decoding as 4bpp by default.")
            expected_payload = (max(width, 8) * max(height, 8) * 4) // 8

        # Extract top mip-level raw compressed stream
        raw_pvrtc_data = f.read(expected_payload)

    if len(raw_pvrtc_data) != expected_payload:
        raise ValueError("Incomplete PVRTC payload")

    # Decode PVRTC to BGRA raw bytes
    # Signature: decode_pvrtc(bytes, width, height, is2bpp)
    bgra_bytes = texture2ddecoder.decode_pvrtc(raw_pvrtc_data, width, height, is_2bpp)

    # Convert to Pillow image and save
    img = Image.frombytes("RGBA", (width, height), bgra_bytes, "raw", "BGRA")
    img.save(output_path)
    print(f"Successfully decoded and saved to: {output_path}")

def encode_texture(input_path, output_path, encoding):
    cli_format, expected_fourcc, asset_fourcc, _ = ENCODINGS[encoding]
    with TemporaryDirectory(dir=output_path.parent) as tmp:
        dds_path = Path(tmp) / "texture.dds"
        subprocess.run(
            ["bash", str(COMPRESSONATOR), "-noprogress", "-fd", cli_format,
             str(input_path.resolve()), str(dds_path.resolve())],
            check=True,
        )
        with dds_path.open("r+b") as dds:
            header = dds.read(128)
            if (len(header) != 128 or header[:4] != b"DDS "
                    or header[84:88] != expected_fourcc or not dds.read(1)):
                raise ValueError(f"Compressonator produced invalid {encoding.upper()} DDS output")
            if asset_fourcc != expected_fourcc:
                dds.seek(84)
                dds.write(asset_fourcc)
        # Publish the completed file without replacing an existing asset.
        output_path.hardlink_to(dds_path)
    print(f"Converted {input_path} to {encoding.upper()} at {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Find ATC and ETC1 assets and decode .ddspvr textures.",
    )
    parser.add_argument(
        "inputs", nargs="*", metavar="APK or FORMAT",
        help="APK to extract, followed by optional encodings: etc1, atc, atci. "
             "Omit the APK to scan ./assets.",
    )
    parser.add_argument(
        "-o", "--output", type=Path,
        help="Apktool extraction directory (default: <APK stem>.out beside the APK)",
    )
    args = parser.parse_intermixed_args()
    encodings = set(args.inputs) & ENCODINGS.keys()
    apk_inputs = [Path(value) for value in args.inputs if value not in ENCODINGS]
    if len(apk_inputs) > 1 or any(path.suffix.lower() != ".apk" for path in apk_inputs):
        parser.error("expected at most one APK path and encodings etc1, atc, or atci")
    if args.output is not None and not apk_inputs:
        parser.error("--output requires an APK")
    if {"atc", "atci"} <= encodings:
        parser.error("atc and atci both produce .ddsatc files. Choose one.")

    assets = Path("assets")
    if apk_inputs:
        apk_path = apk_inputs[0]
        if not apk_path.is_file():
            parser.error(f"APK not found: {apk_path}")
        output_dir = args.output or apk_path.with_suffix(".out")
        if output_dir.exists() or output_dir.is_symlink():
            parser.error(f"extraction directory already exists: {output_dir}")
        assets = extract_assets(apk_path, output_dir)
        if not assets.is_dir():
            print(f"No assets directory in {output_dir}")
            return 0
    elif not assets.is_dir():
        parser.error("assets directory not found. Pass an APK or run from a directory containing assets/.")

    files = sorted(path for path in assets.rglob("*") if path.is_file() and not path.is_symlink())
    pvr_files = []
    existing_count = 0
    for path in files:
        texture_format = existing_texture_format(path)
        if texture_format:
            existing_count += 1
            print(f"Found {texture_format}: {path.relative_to(assets)}")
        elif path.suffix.lower() == ".ddspvr":
            pvr_files.append(path)
    print(f"Found {existing_count} existing ATC/ETC1 asset(s) in {assets}")

    failures = 0
    for path in pvr_files:
        png_path = path.with_suffix(".png")
        try:
            decode_dds_pvr(path, png_path)
        except (OSError, ValueError, RuntimeError) as error:
            print(f"{path}: {error}", file=sys.stderr)
            failures += 1
            continue
        for encoding, (_, _, _, suffix) in ENCODINGS.items():
            if encoding not in encodings:
                continue
            output_path = path.with_suffix(suffix)
            if output_path.exists() or output_path.is_symlink():
                print(f"Keeping existing asset: {output_path}")
                continue
            try:
                encode_texture(png_path, output_path, encoding)
            except FileExistsError:
                print(f"Keeping existing asset: {output_path}")
            except (OSError, ValueError, subprocess.CalledProcessError) as error:
                print(f"{output_path}: {error}", file=sys.stderr)
                failures += 1
    return int(bool(failures))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
