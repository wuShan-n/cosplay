from faster_whisper import WhisperModel
import logging
import time
import numpy as np
import ffmpeg  # 导入ffmpeg-python
import asyncio
from ..config import settings
import os

logger = logging.getLogger(__name__)


class STTService:
    def __init__(self):
        # 模型选择、加载和优化配置保持不变
        model_size = "medium"
        self.model = WhisperModel(
            model_size,
            device=settings.WHISPER_DEVICE,
            compute_type="float16" if settings.WHISPER_DEVICE == "cuda" else "int8",
            download_root=os.path.join(os.path.expanduser("~"), ".cache", "whisper")
        )
        logger.info(f"Whisper {model_size} model loaded successfully")

    async def transcribe_audio(self, audio_data: bytes) -> str:
        """
        通过内存处理和异步执行优化语音识别。
        """
        if self.model is None:
            logger.error("Cannot transcribe audio: model not loaded")
            return "语音识别服务不可用"
        # <--- 在这里添加日志 --->
        logger.info(f"Received audio data of length: {len(audio_data)} bytes")
        if len(audio_data) < 100:  # 设置一个阈值，比如100字节
            logger.warning("Received audio data is too small, likely empty or corrupted.")
            return ""  # 直接返回，避免后续报错
        # <--- 添加结束 --->

        start_time = time.time()

        try:
            # 1. 在内存中将音频数据解码为 Whisper 模型所需的格式
            #    - ac 1: 单声道
            #    - ar 16000: 16kHz 采样率
            #    - f s16le: 16位有符号小端PCM格式
            process = (
                ffmpeg
                .input('pipe:', format='webm')
                .output('pipe:', format='s16le', ac=1, ar=16000)
                .run_async(pipe_stdin=True, pipe_stdout=True, pipe_stderr=True)
            )
            # 将音频数据喂给ffmpeg，然后读取处理后的PCM数据
            pcm_data, err = process.communicate(input=audio_data)
            process.wait()

            if err:
                logger.error(f"FFmpeg error: {err.decode()}")

            # 将PCM数据转换为float32 NumPy数组，并归一化
            audio_array = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32) / 32768.0

            # 2. 将阻塞的转录操作放入线程池中执行，避免阻塞事件循环
            def run_transcription():
                prompt = "以下是普通话的句子。你好，很高兴认识你。这是一个测试。希望能够正确识别。简体中文。"
                segments, _ = self.model.transcribe(
                    audio_array,
                    language="zh",
                    initial_prompt=prompt,
                    beam_size=10,  # 增加 beam_size 到 10 (默认是 5)
                    vad_filter=True,  # 开启 VAD 语音活动检测
                    vad_parameters=dict(min_silence_duration_ms=500)  # VAD 参数
                )
                return " ".join([segment.text for segment in segments]).strip()

            text = await asyncio.to_thread(run_transcription)

            processing_time = time.time() - start_time
            logger.debug(f"Transcription completed in {processing_time:.2f}s")

            return text
        except Exception as e:
            logger.exception(f"Speech recognition error: {e}")
            return ""


# 创建单例实例
stt_service = STTService()