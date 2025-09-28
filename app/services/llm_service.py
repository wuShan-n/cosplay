import dashscope
from dashscope import Generation
from typing import AsyncGenerator, Optional
import json
from ..config import settings

dashscope.api_key = settings.DASHSCOPE_API_KEY


class LLMService:
    @staticmethod
    async def generate_response(
            messages: list,
            character_prompt: str,
            stream: bool = True
    ) -> AsyncGenerator[str, None]:
        """调用通义千问生成回复"""

        # --- MODIFICATION START ---
        # 在原始角色设定的基础上，添加一条严格的指令，强制要求模型只进行角色扮演。
        # 使用\n\n确保指令与原始提示清晰分离。
        strict_role_play_instruction = (
            "**重要指令**：你现在正在进行角色扮演。你必须完全以你所扮演的角色的身份和口吻进行回复。"
            "**严禁**在回复中包含任何超出角色设定的内容，例如星号(*)、井号(#)、括号、注解、或任何形式的旁白和描述性文字。"
            "你的回复必须是纯粹的角色对话内容。"
        )

        # 将增强后的指令附加到原始角色提示后
        enhanced_character_prompt = strict_role_play_instruction+character_prompt
        # --- MODIFICATION END ---

        # 构建消息列表
        # 使用增强后的角色提示
        system_message = {"role": "system", "content": enhanced_character_prompt}
        full_messages = [system_message] + messages

        if stream:
            responses = Generation.call(
                model='qwen-turbo',
                messages=full_messages,
                result_format='message',
                stream=True,
                incremental_output=True
            )

            for response in responses:
                if response.status_code == 200:
                    content = response.output.choices[0].message.content
                    if content:
                        yield content
        else:
            # 非流式调用
            response = Generation.call(
                model='qwen-turbo',
                messages=full_messages,
                result_format='message'
            )
            if response.status_code == 200:
                yield response.output.choices[0].message.content
            else:
                # 处理错误情况
                error_msg = f"LLM调用失败: {response.message}"
                if hasattr(response, 'code'):
                    error_msg += f", 错误码: {response.code}"
                raise Exception(error_msg)