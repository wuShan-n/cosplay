import logging
from ..services.llm_service import LLMService

logger = logging.getLogger(__name__)


class ContextAgent:
    @staticmethod
    async def generate_summary(conversation_text: str) -> str:
        """
        使用LLM生成对话摘要，包括情感分析和上下文提示

        参数:
            conversation_text: 对话文本，每行格式为"角色: 内容"

        返回:
            生成的摘要文本
        """
        try:
            # 构建提示
            prompt = f"""请根据以下对话内容生成一个简洁的摘要，包括情感分析和关键信息提取，
以便后续对话能够保持连贯性。摘要长度不超过1000字符。

对话内容:
{conversation_text}

摘要:
"""

            # 使用LLM生成摘要
            summary = ""
            async for chunk in LLMService.generate_response(
                    messages=[{"role": "user", "content": prompt}],
                    character_prompt="你是一个专业的对话摘要助手，能够从对话中提取关键信息，分析情感，并生成简洁的摘要。"
            ):
                summary += chunk

            return summary.strip()

        except Exception as e:
            logger.error(f"生成摘要时出错: {e}")
            # 返回一个简单的摘要作为备选
            return "对话摘要生成失败，请检查日志。"