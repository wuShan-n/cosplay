import edge_tts
import tempfile
import os
from typing import Optional


class TTSService:
    @staticmethod
    async def synthesize(
            text: str,
            voice_id: str = "zh-CN-XiaoxiaoNeural"
    ) -> bytes:
        """将文字转换为语音"""
        communicate = edge_tts.Communicate(text, voice_id)

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_file:
            tmp_path = tmp_file.name

        try:
            await communicate.save(tmp_path)

            with open(tmp_path, 'rb') as f:
                audio_data = f.read()

            return audio_data
        finally:
            os.unlink(tmp_path)

    @staticmethod
    async def get_voices(language: str = "zh") -> list:
        """获取可用的语音列表"""
        voices = await edge_tts.list_voices()
        if language:
            voices = [v for v in voices if v["Locale"].startswith(language)]
        return voices


tts_service = TTSService()