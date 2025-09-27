# app/services/indextts2_service.py
import aiohttp
import base64
import logging
from typing import Optional
import os

logger = logging.getLogger(__name__)


class IndexTTS2Service:
    def __init__(self, api_url: str = None):
        """
        初始化IndexTTS2服务

        参数:
            api_url: IndexTTS2 API的URL，默认从环境变量读取
        """
        self.api_url = api_url or os.getenv("INDEXTTS2_API_URL", "http://localhost:6006")
        self.endpoint = f"{self.api_url}/tts"
        logger.info(f"IndexTTS2 Service initialized with URL: {self.api_url}")

        # 预设的音色参考音频（Base64编码）
        # 你可以在这里预先准备一些音色样本
        self.voice_presets = {}

    async def add_voice_preset(self, name: str, audio_path: str):
        """
        添加预设音色

        参数:
            name: 音色名称
            audio_path: 音频文件路径
        """
        try:
            with open(audio_path, 'rb') as f:
                audio_data = f.read()
                self.voice_presets[name] = base64.b64encode(audio_data).decode()
                logger.info(f"Added voice preset: {name}")
        except Exception as e:
            logger.error(f"Failed to add voice preset {name}: {e}")

    async def synthesize(
            self,
            text: str,
            voice_id: str = None,
            voice_audio_base64: str = None,
            emo_text: Optional[str] = None,
            emo_audio_base64: Optional[str] = None,
            emotion_vector: Optional[list] = None,
            emo_alpha: float = 0.7,
            use_random: bool = False
    ) -> bytes:
        """
        使用IndexTTS2合成语音

        参数:
            text: 要合成的文本
            voice_id: 预设音色ID（从voice_presets中查找）
            voice_audio_base64: 直接提供的音色参考音频(base64)
            emo_text: 情绪文本描述
            emo_audio_base64: 情绪参考音频(base64)
            emotion_vector: 8维情绪向量
            emo_alpha: 情绪强度
            use_random: 是否使用随机性

        返回:
            合成的音频数据(bytes)
        """

        # 确定音色来源
        if voice_audio_base64:
            voice_base64 = voice_audio_base64
        elif voice_id and voice_id in self.voice_presets:
            voice_base64 = self.voice_presets[voice_id]
        else:
            # 如果没有提供音色，使用默认音色或抛出异常
            if "default" in self.voice_presets:
                voice_base64 = self.voice_presets["default"]
                logger.warning(f"Voice {voice_id} not found, using default voice")
            else:
                raise ValueError("No voice provided and no default voice available")

        # 构建请求数据
        request_data = {
            "text": text,
            "voice_base64": voice_base64,
            "emo_text": emo_text,
            "emo_audio_base64": emo_audio_base64,
            "emotion_vector": emotion_vector,
            "emo_alpha": emo_alpha,
            "use_random": use_random
        }

        # 移除None值
        request_data = {k: v for k, v in request_data.items() if v is not None}

        # 发送请求
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                        self.endpoint,
                        json=request_data,
                        timeout=aiohttp.ClientTimeout(total=60)  # 60秒超时
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        if result.get("success"):
                            audio_base64 = result["audio_base64"]
                            audio_bytes = base64.b64decode(audio_base64)
                            logger.info(f"Successfully synthesized {len(text)} characters")
                            return audio_bytes
                        else:
                            raise Exception("Synthesis failed: API returned success=false")
                    else:
                        error_text = await response.text()
                        raise Exception(f"API error {response.status}: {error_text}")

            except aiohttp.ClientError as e:
                logger.error(f"Network error calling IndexTTS2: {e}")
                raise Exception(f"Failed to connect to IndexTTS2 API: {e}")
            except Exception as e:
                logger.error(f"Error in IndexTTS2 synthesis: {e}")
                raise


# 创建单例实例
indextts2_service = IndexTTS2Service()