from faster_whisper import WhisperModel
import tempfile
import os
from ..config import settings


class STTService:
    def __init__(self):
        self.model = WhisperModel(
            settings.WHISPER_MODEL,
            device=settings.WHISPER_DEVICE,
            compute_type="int8"
        )

    async def transcribe(self, audio_data: bytes) -> str:
        """将音频转换为文字"""
        # 保存临时音频文件
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp_file:
            tmp_file.write(audio_data)
            tmp_path = tmp_file.name

        try:
            # 进行语音识别
            segments, _ = self.model.transcribe(
                tmp_path,
                language="zh",
                beam_size=5
            )

            text = " ".join([segment.text for segment in segments])
            return text.strip()
        finally:
            # 清理临时文件
            os.unlink(tmp_path)


stt_service = STTService()