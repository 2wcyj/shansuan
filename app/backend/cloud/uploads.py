"""One bounded multipart photo in memory, without UploadFile's plaintext disk spool."""
from python_multipart import MultipartParser
from python_multipart.multipart import parse_options_header

from app.backend.cloud.images import MAX_UPLOAD
from app.backend.errors import AppError


async def read_photo_upload(request):
    kind, options = parse_options_header(request.headers.get('content-type', ''))
    boundary = options.get(b'boundary', b'')
    if kind != b'multipart/form-data' or not 1 <= len(boundary) <= 70:
        raise AppError('请通过文件上传选择一张图片', 'image_form')
    limit = MAX_UPLOAD + 64 * 1024
    length = request.headers.get('content-length')
    if length:
        try:
            if not 0 <= int(length) <= limit:
                raise AppError('上传内容超过12MB限制', 'image_size', 413)
        except ValueError:
            raise AppError('上传长度无效', 'image_form') from None
    content = bytearray()
    header_name, header_value = bytearray(), bytearray()
    headers = {}
    parts, header_bytes, seen_end = 0, 0, False
    mime = ''

    def part_begin():
        nonlocal parts
        parts += 1
        if parts != 1:
            raise AppError('每次只能上传一张图片', 'image_form')

    def append_header(target, data, start, end):
        nonlocal header_bytes
        header_bytes += end-start
        if header_bytes > 8192:
            raise AppError('图片上传头部过长', 'image_form')
        target.extend(data[start:end])

    def header_end():
        name = bytes(header_name).lower()
        if name in headers:
            raise AppError('图片上传头部重复', 'image_form')
        headers[name] = bytes(header_value)
        header_name.clear()
        header_value.clear()

    def headers_finished():
        nonlocal mime
        disposition, params = parse_options_header(headers.get(b'content-disposition', b''))
        if disposition != b'form-data' or params.get(b'name') != b'file' or b'filename' not in params:
            raise AppError('请选择图片文件', 'image_form')
        try:
            mime = headers.get(b'content-type', b'').decode('ascii').lower()
        except UnicodeError:
            raise AppError('图片类型无效', 'image_type') from None

    def part_data(data, start, end):
        if len(content)+end-start > MAX_UPLOAD:
            raise AppError('请选择不超过12MB的图片', 'image_size', 413)
        content.extend(data[start:end])

    def end():
        nonlocal seen_end
        seen_end = True

    parser = MultipartParser(boundary, {'on_part_begin':part_begin,
        'on_header_field':lambda data, start, end:append_header(header_name, data, start, end),
        'on_header_value':lambda data, start, end:append_header(header_value, data, start, end),
        'on_header_end':header_end, 'on_headers_finished':headers_finished,
        'on_part_data':part_data, 'on_end':end})
    received = 0
    try:
        async for chunk in request.stream():
            received += len(chunk)
            if received > limit:
                raise AppError('上传内容超过12MB限制', 'image_size', 413)
            parser.write(chunk)
        parser.finalize()
    except AppError:
        raise
    except Exception:
        raise AppError('图片上传不完整或格式无效，请重试', 'image_form') from None
    finally:
        parser.close()
    if not seen_end or parts != 1:
        raise AppError('图片上传不完整，请重试', 'image_form')
    return bytes(content), mime
