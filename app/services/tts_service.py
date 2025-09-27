import edge_tts
import tempfile
import os
import logging
from typing import Optional, Literal
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

    async def synthesize(
            self,
            text: str,
            voice_id: str = "zh-CN-XiaoxiaoNeural",
            engine: Optional[TTSEngine] = None,
            **kwargs
    ) -> bytes:
        """
        统一的TTS接口，支持多种引擎

        参数:
            text: 要合成的文本
            voice_id: 音色ID
            engine: TTS引擎类型，None则使用默认引擎
            **kwargs: 传递给具体引擎的额外参数

        返回:
            合成的音频数据(bytes)
        """
        engine = engine or self.default_engine

        if engine == TTSEngine.EDGE_TTS:
            return await self._synthesize_edge_tts(text, voice_id)
        elif engine == TTSEngine.INDEXTTS2:
            return await self._synthesize_indextts2(text, voice_id, **kwargs)
        else:
            raise ValueError(f"Unsupported TTS engine: {engine}")

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

    async def _synthesize_indextts2(
            self,
            text: str,
            voice_id: str,
            **kwargs
    ) -> bytes:
        """
        使用IndexTTS2合成语音

        额外参数通过kwargs传递:
            - voice_audio_base64: 音色参考音频
            - emo_text: 情绪文本
            - emo_audio_base64: 情绪音频
            - emotion_vector: 情绪向量
            - emo_alpha: 情绪强度
            - use_random: 随机性
        """
        logger.debug(f"Using IndexTTS2 to synthesize {len(text)} characters")
        return await self.indextts2_service.synthesize(
            text=text,
            voice_id=voice_id,
            **kwargs
        )

    def set_default_engine(self, engine: TTSEngine):
        """设置默认TTS引擎"""
        self.default_engine = engine
        logger.info(f"Default TTS engine set to: {engine}")


# 创建单例实例
tts_service = TTSService()