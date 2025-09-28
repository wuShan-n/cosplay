# app/services/indextts2_service.py
import base64
import logging
import os
import re
from typing import Optional, List

import aiohttp

from app.models import Character

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

    async def synthesize(
            self,
            text: str,
            voice_audio_url: Optional[str] = None,  # (*** 新增 ***)
            emo_text: Optional[str] = None,
            emo_audio_url: Optional[str] = None,  # (*** 新增 ***)
            emotion_vector: Optional[List[float]] = None,
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
        # 构建请求数据
        request_data = {
            "text": text,
            "voice_base64": await self._download_audio_as_base64(voice_audio_url),
            "emo_text": emo_text,
            "emo_audio_base64": await self._download_audio_as_base64(emo_audio_url),
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

    # (*** 新增辅助函数 ***)
    async def _download_audio_as_base64(self, url: str) -> Optional[str]:
        """从URL下载音频并编码为Base64"""
        if not url:
            return None
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=30) as response:
                    if response.status == 200:
                        audio_bytes = await response.read()
                        return base64.b64encode(audio_bytes).decode('utf-8')
                    else:
                        logger.error(f"Failed to download audio from {url}, status: {response.status}")
                        return None
        except Exception as e:
            logger.error(f"Error downloading audio from {url}: {e}")
            return None


    def extract_emotion_and_clean_text(self,text):
        """
        从文本中提取情感/动作描述，并返回清理后的文本。
        例如: "好的*开心*" -> ("开心", "好的")
        """
        # 正则表达式，用于查找并捕获 *...* 或 (...) 等模式中的内容
        pattern = r'[\*#【】\[\]\(\)]([^\*#【】\[\]\(\)]*)[\*#【】\[\]\(\)]'

        match = re.search(pattern, text)

        emotion = None
        clean_text = text

        if match:
            # 提取捕获组的内容作为情感指令
            emotion = match.group(1)
            # 从原始文本中移除整个匹配项，得到纯净文本
            clean_text = re.sub(pattern, '', text).strip()

        return emotion, clean_text

    async def synthesize_from_character(self, text: str, character: Character) -> bytes:
        """
        根据角色配置和输入文本，提取情感并合成语音。
        这是一个高层级的方法，封装了从角色准备参数到调用的完整逻辑。

        参数:
            text: 完整的AI生成文本，可能包含情感标记。
            character: 角色对象，包含TTS引擎和配置信息。

        返回:
            合成的音频数据(bytes)
        """
        tts_config = character.tts_config or {}

        # 1. 从文本中提取情感指令
        extracted_emotion, clean_text = self.extract_emotion_and_clean_text(text)

        # 2. 决定最终使用的情感文本
        # 优先使用从文本中实时提取出的情感
        final_emo_text = extracted_emotion or tts_config.get("emo_text")

        if extracted_emotion:
            logger.info(f"从文本中提取到情感指令: {extracted_emotion}")

        # 3. 调用底层的合成方法
        audio_data = await self.synthesize(
            text=text,  # IndexTTS2 API通常需要包含情感标记的原始文本
            voice_audio_url=tts_config.get("voice_audio_url"),
            emo_audio_url=tts_config.get("emo_audio_url"),
            emo_text=final_emo_text,
            emo_alpha=tts_config.get("emo_alpha", 0.7),
            emotion_vector=tts_config.get("emotion_vector"),
            use_random=tts_config.get("use_random", False)
        )
        return audio_data


# 创建单例实例
indextts2_service = IndexTTS2Service()
