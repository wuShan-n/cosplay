import dashscope
from dashscope import Generation
from typing import AsyncGenerator
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
            response = Generation.call(
                model='qwen-turbo',
                messages=full_messages,
                result_format='message'
            )
            if response.status_code == 200:
                yield response.output.choices[0].message.content