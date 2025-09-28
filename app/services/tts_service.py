import edge_tts
import tempfile
import os
import logging
from typing import Optional, Literal, AsyncGenerator
from enum import Enum

logger = logging.getLogger(__name__)


class TTSEngine(str, Enum):
    """TTS引擎类型"""
    EDGE_TTS = "edge_tts"
    INDEXTTS2 = "indextts2"


class TTSService:
    def __init__(self):
        """初始化TTS服务，支持多种引擎"""
        self.default_engine = TTSEngine.EDGE_TTS
        self._indextts2_service = None

    @property
    def indextts2_service(self):
        """延迟加载 IndexTTS2 服务"""
        if self._indextts2_service is None:
            from .indextts2_service import indextts2_service
            self._indextts2_service = indextts2_service
        return self._indextts2_service

    async def synthesize_stream(
            self,
            text: str,
            voice_id: str = "zh-CN-XiaoxiaoNeural",
    ) -> AsyncGenerator[bytes, None]:
        """
        流式TTS接口，逐块生成音频数据
        返回:
            一个异步生成器，用于逐块产出音频数据(bytes)
        """

        communicate = edge_tts.Communicate(text, voice_id)
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                yield chunk["data"]

    async def _synthesize_edge_tts(
            self,
            text: str,
            voice_id: str = "zh-CN-XiaoxiaoNeural"
    ) -> bytes:
        """使用Edge-TTS合成语音"""
        communicate = edge_tts.Communicate(text, voice_id)

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_file:
            tmp_path = tmp_file.name

        try:
            await communicate.save(tmp_path)

            with open(tmp_path, 'rb') as f:
                audio_data = f.read()

            logger.debug(f"Edge-TTS synthesized {len(text)} characters")
            return audio_data
        finally:
            os.unlink(tmp_path)



# 创建单例实例
tts_service = TTSService()