# text_correction_service.py
from typing import Optional
from ..services.llm_service import LLMService


class TextCorrectionService:
    def __init__(self):
        self.llm_service = LLMService()

    async def correct_text(self, raw_text: str, context: Optional[str] = None) -> str:
        """
        调用LLM对文本进行校对和重写

        参数:
            raw_text: 需要校对的原始文本
            context: 可选的上下文信息，帮助LLM更好地理解并进行校正

        返回:
            str: 经过LLM校对和重写后的文本
        """
        # 构建系统提示词
        system_prompt = """你是一个文本校对专家。你的任务是将用户输入的语音识别文本进行校对，修正其中的错别字、语法错误和标点符号，使其变得流畅自然。

        请严格遵守以下规则：
        1. **保持原意**：绝对不要改变句子原本想要表达的意思。
        2. **只做最小必要修改**：只修改错误的字词和语法，不要添加额外内容或进行意译。
        3. **输出要求**：只返回修正后的文本，不要有任何额外的解释、说明或标记。

        如果文本已经是流畅正确的中文，请直接返回原文本。"""

        # 构建用户输入
        user_input = f"请校对以下文本：{raw_text}"
        if context:
            user_input = f"上下文：{context}\n\n请根据以上上下文校对以下文本：{raw_text}"

        # 调用LLM进行校对
        try:
            corrected_text = ""
            async for chunk in self.llm_service.generate_response(
                    messages=[{"role": "user", "content": user_input}],
                    character_prompt=system_prompt,
                    stream=False
            ):
                corrected_text += chunk

            # 确保返回的文本不为空
            return corrected_text.strip() if corrected_text.strip() else raw_text
        except Exception as e:
            # 如果LLM调用失败，返回原始文本作为降级方案
            print(f"LLM校对错误: {e}")
            return raw_text


# 创建单例实例
text_correction_service = TextCorrectionService()