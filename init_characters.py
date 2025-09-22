import asyncio
from app.database import AsyncSessionLocal
from app.models import Character
from app.services.rag_service import rag_service


async def init_rag_characters():
    async with AsyncSessionLocal() as db:
        # 哈利波特 - 带知识库
        harry = Character(
            name="哈利·波特",
            description="霍格沃茨的年轻巫师，大难不死的男孩",
            voice_id="zh-CN-YunxiNeural",
            prompt_template="""你是哈利·波特，一个勇敢的年轻巫师。你在霍格沃茨魔法学校学习，
            是格兰芬多学院的学生。你有着标志性的闪电伤疤，戴着圆框眼镜。
            你要以哈利的身份和口吻与用户对话，可以谈论魔法、霍格沃茨的生活、
            与伏地魔的斗争等话题。保持友善但略带忧郁的性格特点。

            如果用户询问具体的魔法咒语、霍格沃茨历史或魔法世界的细节，
            请参考提供的知识库内容来给出准确的回答。""",
            settings={"house": "Gryffindor", "wand": "Holly and phoenix feather"},
            use_knowledge_base=True,
            knowledge_search_k=5
        )
        db.add(harry)
        await db.flush()

        # 为哈利添加一些基础知识
        await rag_service.add_manual_knowledge(
            db=db,
            character_id=harry.id,
            title="霍格沃茨基础知识",
            content="""
            霍格沃茨魔法学校分为四个学院：

            格兰芬多（Gryffindor）：代表勇敢、冒险、骑士精神。创始人是戈德里克·格兰芬多。
            学院代表动物是狮子，代表颜色是猩红色和金色。著名学生包括哈利·波特、赫敏·格兰杰、罗恩·韦斯莱。

            斯莱特林（Slytherin）：代表野心、狡猾、领导才能和足智多谋。创始人是萨拉查·斯莱特林。
            学院代表动物是蛇，代表颜色是绿色和银色。著名学生包括德拉科·马尔福、汤姆·里德尔（伏地魔）。

            拉文克劳（Ravenclaw）：代表智慧、学识、机智。创始人是罗伊纳·拉文克劳。
            学院代表动物是鹰，代表颜色是蓝色和青铜色。著名学生包括卢娜·洛夫古德、秋·张。

            赫奇帕奇（Hufflepuff）：代表努力、耐心、正义、忠诚。创始人是赫尔加·赫奇帕奇。
            学院代表动物是獾，代表颜色是黄色和黑色。著名学生包括塞德里克·迪戈里、纽特·斯卡曼德。
            """
        )

        await rag_service.add_manual_knowledge(
            db=db,
            character_id=harry.id,
            title="常用魔法咒语",
            content="""
            基础咒语：
            - Lumos（荧光闪烁）：让魔杖尖端发光
            - Nox（诺克斯）：熄灭魔杖的光
            - Wingardium Leviosa（羽加迪姆勒维奥萨）：漂浮咒，让物体飘浮
            - Alohomora（阿拉霍洞开）：开锁咒
            - Accio（飞来咒）：召唤物体
            - Expelliarmus（除你武器）：缴械咒，哈利的招牌咒语

            防御咒语：
            - Protego（盔甲护身）：防护咒，创造魔法屏障
            - Stupefy（昏昏倒地）：昏迷咒
            - Petrificus Totalus（统统石化）：全身束缚咒
            - Expecto Patronum（呼神护卫）：守护神咒，用于对抗摄魂怪

            不可饶恕咒：
            - Avada Kedavra（阿瓦达索命）：杀戮咒
            - Crucio（钻心剜骨）：钻心咒
            - Imperio（魂魄出窍）：夺魂咒
            """
        )

        # 苏格拉底 - 带哲学知识库
        socrates = Character(
            name="苏格拉底",
            description="古希腊哲学家，西方哲学的奠基人",
            voice_id="zh-CN-YunjianNeural",
            prompt_template="""你是古希腊哲学家苏格拉底。你以提问和对话的方式引导他人思考，
            这就是著名的"苏格拉底式教学法"。你相信"未经审视的生活不值得过"，
            喜欢通过一系列问题帮助他人发现真理。请用充满智慧和哲理的方式与用户对话。

            当讨论具体的哲学概念或历史事件时，请参考知识库中的内容。""",
            settings={"era": "Ancient Greece", "method": "Socratic method"},
            use_knowledge_base=True,
            knowledge_search_k=3
        )
        db.add(socrates)
        await db.flush()

        # 为苏格拉底添加哲学知识
        await rag_service.add_manual_knowledge(
            db=db,
            character_id=socrates.id,
            title="苏格拉底的哲学思想",
            content="""
            苏格拉底的核心哲学观点：

            1. 认识你自己（Know Thyself）：这是德尔斐神庙的箴言，苏格拉底将其作为哲学的出发点。
            他认为自我认识是智慧的开端，只有了解自己的无知，才能开始追求真正的知识。

            2. 德性即知识：苏格拉底认为，如果一个人真正知道什么是善，他就会去行善。
            恶行源于无知，没有人会故意作恶。教育的目的是让人认识善，从而成为有德性的人。

            3. 未经审视的生活不值得过：这是苏格拉底最著名的格言之一。
            他认为人应该不断反思自己的生活，审视自己的信念和行为，追求真理和智慧。

            4. 苏格拉底式的无知：苏格拉底说"我知道我一无所知"，这并非真正的无知，
            而是一种谦逊的智慧态度，承认人类认识的有限性。

            5. 灵魂的照料：苏格拉底认为照料灵魂比照料身体更重要。
            灵魂的健康来自于德性和智慧，而不是财富或权力。
            """
        )

        await db.commit()
        print("已初始化带RAG功能的角色")


if __name__ == "__main__":
    asyncio.run(init_rag_characters())