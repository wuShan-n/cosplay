# app/services/llm_service.py (更新版本)
import dashscope
from dashscope import Generation
from typing import AsyncGenerator, List
import json
from ..config import settings
from .rag_service import rag_service

dashscope.api_key = settings.DASHSCOPE_API_KEY


class LLMService:
    @staticmethod
    async def generate_response(
            messages: list,
            character_prompt: str,
            character_id: int = None,
            stream: bool = True,
            use_rag: bool = True
    ) -> AsyncGenerator[str, None]:
        """调用通义千问生成回复，支持RAG增强"""

        # 如果启用RAG且有角色ID，则搜索相关知识
        context = ""
        if use_rag and character_id and messages:
            last_user_message = ""
            for msg in reversed(messages):
                if msg.get("role") == "user":
                    last_user_message = msg.get("content", "")
                    break

            if last_user_message:
                # 在知识库中搜索相关信息
                knowledge_chunks = await rag_service.search_knowledge(
                    character_id,
                    last_user_message,
                    k=3
                )

                if knowledge_chunks:
                    context = "\n\n相关背景知识：\n" + "\n".join([
                        f"- {chunk}" for chunk in knowledge_chunks
                    ])

        # 构建增强的系统提示
        enhanced_prompt = character_prompt
        if context:
            enhanced_prompt += f"\n\n{context}\n\n请根据以上背景知识回答用户的问题，保持角色特色的同时确保信息的准确性。"

        # 构建消息列表
        system_message = {"role": "system", "content": enhanced_prompt}
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

    @staticmethod
    async def generate_knowledge_summary(
            character_name: str,
            knowledge_chunks: List[str]
    ) -> str:
        """为角色生成知识库摘要"""
        if not knowledge_chunks:
            return ""

        prompt = f"""
        请为角色"{character_name}"的知识库内容生成一个简洁的摘要，突出关键信息点。

        知识内容：
        {chr(10).join(f"- {chunk}" for chunk in knowledge_chunks)}

        请生成一个150字以内的摘要：
        """

        messages = [{"role": "user", "content": prompt}]

        response = Generation.call(
            model='qwen-turbo',
            messages=messages,
            result_format='message'
        )

        if response.status_code == 200:
            return response.output.choices[0].message.content
        return ""