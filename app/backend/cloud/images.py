"""Bounded image decoding without Windows storage imports or persistent plaintext."""
import io
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError
from app.backend.errors import AppError

MAX_UPLOAD = 12 * 1024 * 1024
_MIMES = {'JPEG':'image/jpeg', 'PNG':'image/png', 'WEBP':'image/webp'}


def normalize_photo(content: bytes, declared_mime: str) -> bytes:
    if not content or len(content) > MAX_UPLOAD:
        raise AppError('请选择不超过12MB的JPG、PNG或WebP图片', 'image_size', 413)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                if image.format not in _MIMES or _MIMES[image.format] != declared_mime:
                    raise AppError('图片实际格式与声明不符，仅支持JPG、PNG和WebP', 'image_type')
                if image.width * image.height > 24_000_000 or getattr(image, 'is_animated', False):
                    raise AppError('请使用不超过2400万像素的静态图片', 'image_invalid')
                image.verify()
            with Image.open(io.BytesIO(content)) as image:
                normalized = ImageOps.exif_transpose(image).convert('RGB')
                normalized.thumbnail((1600, 1600))
                output = io.BytesIO()
                normalized.save(output, format='JPEG', quality=88)
                return output.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError,
            Image.DecompressionBombWarning):
        raise AppError('图片损坏或像素过大，请换一张图片', 'image_invalid') from None
