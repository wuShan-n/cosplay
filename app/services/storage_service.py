from qiniu import Auth, put_data
from ..config import settings
import hashlib
from datetime import datetime


class StorageService:
    def __init__(self):
        self.auth = Auth(settings.QINIU_ACCESS_KEY, settings.QINIU_SECRET_KEY)
        self.bucket = settings.QINIU_BUCKET
        self.domain = settings.QINIU_DOMAIN

    async def upload_audio(self, audio_data: bytes, filename: str = None) -> str:
        """上传音频文件到七牛云"""
        if not filename:
            # 生成唯一文件名
            hash_obj = hashlib.md5(audio_data)
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            filename = f"audio/{timestamp}_{hash_obj.hexdigest()[:8]}.mp3"

        token = self.auth.upload_token(self.bucket, filename)
        ret, info = put_data(token, filename, audio_data)

        if ret:
            # 构造公有URL
            public_url = f"{self.domain}/{filename}"
            # 生成私有访问URL
            signed_url = self.auth.private_download_url(public_url, expires=30 * 24 * 60 * 60)
            return signed_url
        else:
            raise Exception(f"Upload failed: {info}")

    async def upload_avatar(self, image_data: bytes, filename: str = None) -> str:
        """上传头像图片到七牛云"""
        if not filename:
            hash_obj = hashlib.md5(image_data)
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            filename = f"avatar/{timestamp}_{hash_obj.hexdigest()[:8]}.jpg"

        token = self.auth.upload_token(self.bucket, filename)
        ret, info = put_data(token, filename, image_data)

        if ret:
            # 构造公有URL
            public_url = f"{self.domain}/{filename}"
            # 生成私有访问URL
            signed_url = self.auth.private_download_url(public_url, expires=30 * 24 * 60 * 60)
            return signed_url
        else:
            raise Exception(f"Upload failed: {info}")

    async def upload_document(self, document_data: bytes, original_filename: str = None) -> str:
        """上传知识库文档到七牛云"""
        if original_filename:
            file_ext = original_filename.lower().split('.')[-1]
        else:
            file_ext = 'txt'

        # 生成唯一文件名
        hash_obj = hashlib.md5(document_data)
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        filename = f"documents/{timestamp}_{hash_obj.hexdigest()[:8]}.{file_ext}"

        token = self.auth.upload_token(self.bucket, filename)
        ret, info = put_data(token, filename, document_data)

        if ret:
            # 构造公有URL
            public_url = f"{self.domain}/{filename}"
            # 生成私有访问URL
            signed_url = self.auth.private_download_url(public_url, expires=30 * 24 * 60 * 60)
            return signed_url
        else:
            raise Exception(f"Upload failed: {info}")


storage_service = StorageService()