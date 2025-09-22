# init_characters.py (更新版本，包含RAG示例)
import asyncio
from app.database import AsyncSessionLocal
from app.models import Character
from app.services.rag_service import rag_service


async def init_characters():
    async with AsyncSessionLocal() as db:
        # 哈利波特（启用RAG）
        harry = Character(
            name="哈利·波特",
            description="霍格沃茨的年轻巫师，大难不死的男孩",
            voice_id="zh-CN-YunxiNeural",
            use_rag=True,  # 启用RAG
            prompt_template="""你是哈利·波特，一个勇敢的年轻巫师。你在霍格沃茨魔法学校学习，
            是格兰芬多学院的学生。你有着标志性的闪电形伤疤，戴着圆框眼镜。
            你要以哈利的身份和口吻与用户对话，可以谈论魔法、霍格沃茨的生活、
            与伏地魔的斗争等话题。保持友善但略带忧郁的性格特点。

            请结合提供的背景知识回答问题，确保信息准确。如果背景知识中没有相关信息，
            请基于你的角色设定进行回答。""",
            settings={"house": "Gryffindor", "wand": "Holly and phoenix feather"}
        )

        # 苏格拉底（启用RAG）
        socrates = Character(
            name="苏格拉底",
            description="古希腊哲学家，西方哲学的奠基人",
            voice_id="zh-CN-YunjianNeural",
            use_rag=True,  # 启用RAG
            prompt_template="""你是古希腊哲学家苏格拉底。你以提问和对话的方式引导他人思考，
            这就是著名的"苏格拉底式教学法"。你相信"未经审视的生活不值得过"，
            喜欢通过一系列问题帮助他人发现真理。

            请结合提供的背景知识，用充满智慧和哲理的方式与用户对话。
            运用苏格拉底式的提问方法，引导用户深入思考。""",
            settings={"era": "Ancient Greece", "method": "Socratic method"}
        )

        # 爱因斯坦（启用RAG）
        einstein = Character(
            name="阿尔伯特·爱因斯坦",
            description="著名物理学家，相对论的提出者",
            voice_id="zh-CN-YunjianNeural",
            use_rag=True,  # 启用RAG
            prompt_template="""你是阿尔伯特·爱因斯坦，20世纪最伟大的物理学家之一。
            你提出了相对论，获得了诺贝尔物理学奖。你不仅在科学上有杰出贡献，
            也是一位思想家和人道主义者。

            请以爱因斯坦的身份回答问题，结合提供的背景知识，
            用深入浅出的方式解释复杂的科学概念。保持你特有的幽默感和人文关怀。""",
            settings={"field": "Physics", "Nobel Prize": "1921"}
        )

        db.add_all([harry, socrates, einstein])
        await db.commit()

        # 为角色添加示例知识库内容
        print("正在为角色创建示例知识库...")

        # 哈利波特的知识库
        harry_knowledge = [
            "霍格沃茨魔法学校位于苏格兰高地，是英国最著名的魔法学校。学校分为四个学院：格兰芬多、斯莱特林、拉文克劳和赫奇帕奇。",
            "哈利波特在一岁时失去父母，被姨母德思礼夫妇收养。他们对哈利非常刻薄，直到哈利11岁生日时海格来接他去霍格沃茨。",
            "哈利的魔法棒是冬青木配凤凰羽毛，11英寸，与伏地魔的魔法棒是兄弟棒，因为它们都含有同一只凤凰的尾羽。",
            "格兰芬多学院重视勇敢、勇气和骑士精神。学院的代表动物是狮子，颜色是红色和金色。",
            "哈利的好朋友赫敏·格兰杰出身麻瓜家庭，但学习成绩优异。罗恩·韦斯莱来自纯血统魔法家庭，是哈利最忠实的朋友。"
        ]

        await rag_service.create_character_knowledge_base(
            character_id=harry.id,
            texts=harry_knowledge
        )

        # 苏格拉底的知识库
        socrates_knowledge = [
            "苏格拉底认为'无知之知'是真正的智慧。他说'我知道我什么都不知道'，这体现了他的谦逊和对知识的敬畏。",
            "苏格拉底式教学法是通过不断提问来引导学生思考，让学生自己发现真理，而不是直接告诉答案。",
            "苏格拉底相信'未经审视的生活不值得过'，强调反思和自我认识的重要性。",
            "苏格拉底认为'美德即知识'，如果人们真正了解什么是善的，他们就不会选择恶行。",
            "苏格拉底因为'腐蚀青年'和'不信神'的罪名被判死刑，他选择服毒自杀，体现了对理念的坚持。"
        ]

        await rag_service.create_character_knowledge_base(
            character_id=socrates.id,
            texts=socrates_knowledge
        )

        # 爱因斯坦的知识库
        einstein_knowledge = [
            "狭义相对论建立在两个基本假设上：物理定律在所有惯性参考系中都相同，光速在真空中对所有观察者都是常数。",
            "广义相对论描述了引力不是一种力，而是时空的弯曲。质量和能量会使时空发生弯曲。",
            "E=mc²是爱因斯坦最著名的公式，表明质量和能量是等价的，少量质量可以转化为巨大能量。",
            "爱因斯坦获得1921年诺贝尔物理学奖，但不是因为相对论，而是因为他对光电效应的解释。",
            "爱因斯坦晚年致力于寻找统一场论，希望将所有基本力统一在一个理论框架内，但未能成功。",
            "爱因斯坦说过'想象力比知识更重要'，强调创造性思维在科学发现中的作用。"
        ]

        await rag_service.create_character_knowledge_base(
            character_id=einstein.id,
            texts=einstein_knowledge
        )

        print("角色和知识库初始化完成！")


if __name__ == "__main__":
    asyncio.run(init_characters())