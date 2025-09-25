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

        # 构建消息列表
        system_message = {"role": "system", "content": character_prompt}
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