# stt_service.py
from faster_whisper import WhisperModel
import tempfile
import os
from typing import Optional
import asyncio
import shutil
import logging
import time
from .text_correction_service import text_correction_service
from ..config import settings

logger = logging.getLogger(__name__)


class STTService:
    def __init__(self):
        # 使用小型模型提高速度
        model_size = "small"  # 从medium改为small以提高速度

        try:
            # 加载Whisper模型
            self.model = WhisperModel(
                model_size,
                device=settings.WHISPER_DEVICE,
                compute_type="float16" if settings.WHISPER_DEVICE == "cuda" else "int8",
                download_root=os.path.join(os.path.expanduser("~"), ".cache", "whisper")  # 指定缓存目录
            )
            logger.info(f"Whisper {model_size} model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load Whisper model: {str(e)}")
            # 回退到基础模型
            try:
                self.model = WhisperModel(
                    "base",
                    device=settings.WHISPER_DEVICE,
                    compute_type="float16" if settings.WHISPER_DEVICE == "cuda" else "int8"
                )
                logger.warning("Using base model as fallback")
            except Exception as fallback_error:
                logger.critical(f"Failed to load base model: {str(fallback_error)}")
                self.model = None

    async def _transcribe_audio(self, audio_data: bytes) -> str:
        """语音识别的内部实现，优化速度"""
        # 如果模型加载失败，返回错误信息
        if self.model is None:
            logger.error("Cannot transcribe audio: model not loaded")
            return "语音识别服务不可用"

        start_time = time.time()

        # 创建临时目录用于处理
        temp_dir = tempfile.mkdtemp()
        input_path = os.path.join(temp_dir, "audio_input.webm")

        try:
            # 写入音频数据
            with open(input_path, "wb") as f:
                f.write(audio_data)

            # 使用Whisper进行转录，优化参数以提高速度
            segments, info = self.model.transcribe(
                input_path,
                language="zh",
                beam_size=3,  # 减小beam size以提高速度
                vad_filter=False,  # 禁用VAD过滤以提高速度
                temperature=0.0,  # 使用确定性解码
                best_of=1,  # 减少候选数量
                patience=1.0  # 降低耐心值
            )

            # 拼接转录结果
            text = " ".join([segment.text for segment in segments]).strip()

            processing_time = time.time() - start_time
            logger.debug(f"Transcription completed in {processing_time:.2f}s")

            return text
        except Exception as e:
            logger.exception(f"Speech recognition error: {e}")
            return ""
        finally:
            # 清理临时文件
            shutil.rmtree(temp_dir, ignore_errors=True)

    async def transcribe(self, audio_data: bytes) -> str:
        """将音频转换为文字（原始版本，保持兼容性）"""
        return await self._transcribe_audio(audio_data)

    async def transcribe_and_correct(self, audio_data: bytes, context: Optional[str] = None) -> str:
        """
        将音频转换为文字，并使用LLM进行校对和重写
        """
        raw_text = await self._transcribe_audio(audio_data)

        if not raw_text.strip():
            return raw_text

        corrected_text = await text_correction_service.correct_text(raw_text, context)
        return corrected_text


# 创建单例实例
stt_service = STTService()