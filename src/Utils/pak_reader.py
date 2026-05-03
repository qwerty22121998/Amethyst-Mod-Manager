"""
pak_reader.py
Read metadata from Baldur's Gate 3 .pak files (Larian LSPK v15/v16/v18).

Extracts the meta.lsx XML from inside a .pak archive without needing
lslib or any external tools — only the ``lz4`` Python package is required.

LSPK v18 header (40 bytes):
    4B  signature ("LSPK")
    4B  version (18)
    8B  file_list_offset
    4B  file_list_size
    1B  flags
    1B  priority
   16B  md5
    2B  num_parts
v18 entry (272 bytes):
  256B name | 4B offset_lo | 2B offset_hi | 1B part | 1B flags | 4B size_disk | 4B unc_size

LSPK v15/v16 header (40 bytes):
    4B  signature ("LSPK")
    4B  version (15 or 16)
    8B  file_list_offset
    4B  file_list_size
    2B  num_parts (v16 only; reserved on v15)
    1B  flags
    1B  priority
   16B  md5  (v16 only; v15 ends at byte 24)
v15/v16 entry (296 bytes):
  256B name | 8B offset | 8B size_disk | 8B unc_size | 4B part | 4B flags | 4B crc | 4B unused
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

try:
    import lz4.block as _lz4
except ImportError:
    _lz4 = None  # type: ignore[assignment]

try:
    import zstandard as _zstd
except ImportError:
    _zstd = None  # type: ignore[assignment]

_ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"  # 0xFD2FB528 little-endian

_LSPK_SIGNATURE = 0x4B50534C  # "LSPK" little-endian
_HEADER_SIZE = 40
_ENTRY_SIZE = 272
_ENTRY_SIZE_V15 = 296


def _require_lz4() -> None:
    if _lz4 is None:
        raise ImportError(
            "The 'lz4' package is required to read BG3 .pak files.\n"
            "Install it with:  pip install lz4"
        )


def _lz4_decompress_resilient(data: bytes, uncompressed_size: int) -> bytes:
    """Decompress LZ4 data, retrying with larger buffers if the stored size is wrong.

    Some mod authors produce PAK files where the stored uncompressed_size is
    zero, too small, or otherwise inaccurate.  We first try relative multiples
    of the stored value, then fall back to a range of absolute sizes so that
    even a completely wrong hint still succeeds.
    """
    candidates: list[int] = []

    if uncompressed_size > 0:
        # Try the stored hint and small multiples first.
        for mult in (1, 2, 4, 8, 16, 32):
            candidates.append(uncompressed_size * mult)

    # Absolute fallback sizes: 64 KB → 128 MB in powers of two.
    for exp in range(16, 28):  # 65536 … 134217728
        candidates.append(1 << exp)

    last_exc: Exception | None = None
    seen: set[int] = set()
    for size in candidates:
        if size in seen:
            continue
        seen.add(size)
        try:
            return _lz4.decompress(data, uncompressed_size=size)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc

    raise ValueError(f"LZ4 decompression failed after retries: {last_exc}") from last_exc


def _decompress(data: bytes, flags: int, uncompressed_size: int) -> bytes:
    """Decompress a chunk according to LSPK compression flags.

    Newer versions of Larian's packing tools use zstd for entries even when
    the flags field may nominally indicate LZ4/LZ4HC (method 3 was reassigned
    to zstd in recent tooling).  We detect by magic bytes so both old and new
    archives work correctly.
    """
    method = flags & 0x0F
    if method == 0:
        return data
    if method == 1:
        return zlib.decompress(data)
    # Magic-byte detection overrides the stored method: newer Larian tools
    # write zstd-compressed data regardless of the flag nibble value.
    if len(data) >= 4 and data[:4] == _ZSTD_MAGIC:
        if _zstd is None:
            raise ImportError(
                "The 'zstandard' package is required to read this .pak file.\n"
                "Install it with:  pip install zstandard"
            )
        dctx = _zstd.ZstdDecompressor()
        max_out = max(uncompressed_size * 4, 1 << 20)  # at least 1 MiB headroom
        return dctx.decompress(data, max_output_size=max_out)
    if method in (2, 3):
        # 2 = LZ4, 3 = LZ4HC — decompression is identical for both
        _require_lz4()
        return _lz4_decompress_resilient(data, uncompressed_size)
    raise ValueError(f"Unknown LSPK compression method: {method}")


def _decode_meta_content(content: bytes) -> str:
    # Some PAKs wrap meta.lsx in an extra zlib layer (zlib magic 0x78 ??).
    if len(content) >= 2 and content[0] == 0x78 and content[1] in (
        0x01, 0x5E, 0x9C, 0xDA
    ):
        try:
            content = zlib.decompress(content)
        except zlib.error:
            pass
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("latin-1")


def _extract_meta_v18(f, pak_path: Path) -> str | None:
    f.seek(0)
    header = f.read(_HEADER_SIZE)
    sig, version, file_list_offset, file_list_size, flags, priority = (
        struct.unpack_from("<IIQIBB", header, 0)
    )

    f.seek(file_list_offset)
    num_files = struct.unpack("<I", f.read(4))[0]
    compressed_size = struct.unpack("<I", f.read(4))[0]
    compressed_data = f.read(compressed_size)

    file_list = _lz4_decompress_resilient(
        compressed_data, num_files * _ENTRY_SIZE
    )

    for i in range(num_files):
        base = i * _ENTRY_SIZE
        name_bytes = file_list[base : base + 256]
        nul = name_bytes.find(b"\x00")
        name = name_bytes[:nul].decode("utf-8") if nul >= 0 else name_bytes.decode("utf-8")
        if not name.endswith("meta.lsx"):
            continue

        offset_low = struct.unpack_from("<I", file_list, base + 256)[0]
        offset_high = struct.unpack_from("<H", file_list, base + 260)[0]
        file_offset = offset_low | (offset_high << 32)
        entry_flags = file_list[base + 263]
        size_on_disk = struct.unpack_from("<I", file_list, base + 264)[0]
        unc_size = struct.unpack_from("<I", file_list, base + 268)[0]

        f.seek(file_offset)
        raw = f.read(size_on_disk)
        content = _decompress(raw, entry_flags, unc_size)
        return _decode_meta_content(content)

    return None


def _extract_meta_v15(f, pak_path: Path) -> str | None:
    # v15/v16 share the same entry layout (296 B); the file-list lives at
    # the offset given in the header at bytes 8..15.
    f.seek(8)
    file_list_offset = struct.unpack("<Q", f.read(8))[0]

    f.seek(file_list_offset)
    num_files = struct.unpack("<I", f.read(4))[0]
    compressed_size = struct.unpack("<I", f.read(4))[0]
    compressed_data = f.read(compressed_size)

    file_list = _lz4_decompress_resilient(
        compressed_data, num_files * _ENTRY_SIZE_V15
    )

    for i in range(num_files):
        base = i * _ENTRY_SIZE_V15
        name_bytes = file_list[base : base + 256]
        nul = name_bytes.find(b"\x00")
        name = name_bytes[:nul].decode("utf-8") if nul >= 0 else name_bytes.decode("utf-8")
        if not name.endswith("meta.lsx"):
            continue

        file_offset  = struct.unpack_from("<Q", file_list, base + 256)[0]
        size_on_disk = struct.unpack_from("<Q", file_list, base + 264)[0]
        unc_size     = struct.unpack_from("<Q", file_list, base + 272)[0]
        # archive_part = struct.unpack_from("<I", file_list, base + 280)[0]
        entry_flags  = struct.unpack_from("<I", file_list, base + 284)[0] & 0xFF

        f.seek(file_offset)
        raw = f.read(size_on_disk)
        content = _decompress(raw, entry_flags, unc_size)
        return _decode_meta_content(content)

    return None


def extract_meta_lsx(pak_path: Path | str) -> str | None:
    """Open a BG3 .pak and return the contents of meta.lsx as a string.

    Supports LSPK v15, v16, and v18.  Returns None if the archive does not
    contain a meta.lsx file.  Raises on format errors or missing dependencies.
    """
    _require_lz4()
    pak_path = Path(pak_path)

    with pak_path.open("rb") as f:
        sig_bytes = f.read(8)
        if len(sig_bytes) < 8:
            raise ValueError(f"File too small to be an LSPK archive: {pak_path}")
        sig, version = struct.unpack("<II", sig_bytes)
        if sig != _LSPK_SIGNATURE:
            raise ValueError(
                f"Not an LSPK file (bad signature 0x{sig:08X}): {pak_path}"
            )

        if version >= 18:
            return _extract_meta_v18(f, pak_path)
        if version in (15, 16):
            return _extract_meta_v15(f, pak_path)
        raise ValueError(f"Unsupported LSPK version {version}: {pak_path}")
