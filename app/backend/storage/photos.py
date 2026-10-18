import hashlib
import io
import uuid
from PIL import Image, ImageOps, UnidentifiedImageError
from app.backend.errors import AppError
from .crypto import encrypt, decrypt
from .database import atomic_file

Image.MAX_IMAGE_PIXELS = 24_000_000


def normalize(data):
    if not data or len(data) > 12 * 1024 * 1024:
        raise AppError('请选择不超过12MB的JPG、PNG或WebP图片', 'image_size', 413)
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in {'JPEG','PNG','WEBP'}:
                raise AppError('仅支持JPG、PNG和WebP图片', 'image_type')
            image = ImageOps.exif_transpose(image).convert('RGB')
            image.thumbnail((1600,1600))
            out = io.BytesIO()
            image.save(out,format='JPEG',quality=88)
            return out.getvalue()
    except (UnidentifiedImageError,OSError,Image.DecompressionBombError,Image.DecompressionBombWarning) as error:
        raise AppError('图片损坏或像素过大，请换一张图片', 'image_invalid') from error


class Photos:
    def __init__(self,store):
        self.store = store

    def add(self,data):
        content = normalize(data)
        id = uuid.uuid4().hex
        path = self.store.folder / 'photos' / (id + '.enc')
        try:
            with self.store.atomic():
                atomic_file(path,encrypt(self.store.key,content,id.encode()))
                self.store.conn.execute('INSERT INTO attachments VALUES (?,?,?)',
                                        (id,hashlib.sha256(content).hexdigest(),len(content)))
                analysis = self.store.put('analysis',id,{'photo_id':id,'status':'draft','items':[]})
                self.store.conn.execute('INSERT INTO entity_photos VALUES (?,?,?)',('analysis',id,id))
            return analysis
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    def read(self,id):
        with self.store.lock:
            row = self.store.conn.execute('SELECT * FROM attachments WHERE id=?',(id,)).fetchone()
            if not row:
                raise AppError('照片不存在', 'not_found',404)
            path = self.store.folder / 'photos' / (id + '.enc')
            if not path.is_file():
                raise AppError('照片文件丢失，请从有效备份恢复','storage',503)
            data = decrypt(self.store.key,path.read_bytes(),id.encode())
            if hashlib.sha256(data).hexdigest() != row['sha256']:
                raise AppError('照片完整性校验失败','storage',503)
            return data
