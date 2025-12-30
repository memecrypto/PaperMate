"""Signal detection for user profile auto-update."""

import re
from typing import Literal

SignalType = Literal["mastery", "difficulty", "beginner_question"] | None


class SignalDetector:
    """Detect user intent signals from chat messages for profile updates."""

    # Mastery signals: user indicates understanding
    MASTERY_PATTERNS = [
        r"(我?)(明白|懂|学会|理解|清楚|掌握|会)了",
        r"原来如此",
        r"恍然大悟",
        r"茅塞顿开",
        r"(it'?s|that'?s)\s+(clear|clearer)",
        r"i\s+(understand|get\s+it|got\s+it)",
        r"makes?\s+sense",
        r"now\s+i\s+(see|know|understand)",
    ]

    # Difficulty signals: user indicates confusion
    DIFFICULTY_PATTERNS = [
        r"(不太|没|不|还是不|仍然不)(明白|懂|理解|清楚)",
        r"(有点|太|好|很|挺)(难|深奥|复杂|抽象|绕)",
        r"(看|听|读)(不太?懂|不明白)",
        r"(confused|confusing)",
        r"hard\s+to\s+(understand|follow|grasp)",
        r"(don'?t|doesn'?t|didn'?t)\s+(understand|get)",
        r"(lost|struggling)",
        r"没太?看懂",
        r"能.{0,4}(再|重新).{0,4}(解释|说明|讲)",
        r"^(这|啥|什么)什么意思[？?]?$",  # Very short "什么意思" only (e.g., "这什么意思")
    ]

    # Beginner question patterns: basic "what is X" questions
    # These should match simple concept questions, not complex analytical questions
    BEGINNER_PATTERNS = [
        r"^(什么是|啥是)[A-Za-z\u4e00-\u9fa5]{1,15}[？?]?$",  # "什么是X"
        r"^[A-Za-z]{2,20}(是什么|是啥)[？?]?$",  # English term + "是什么" (e.g., "Attention是什么")
        r"^(what\s+is|what'?s)\s+[a-zA-Z\s]{2,30}\??$",
        r"^(can\s+you\s+explain|please\s+explain)\s+[a-zA-Z\s]{2,30}\??$",
        r"^(能|可以)(解释|说明|介绍)(一下)?[A-Za-z]{2,15}(吗)?[？?]?$",  # "能解释一下CNN吗"
    ]

    _mastery_compiled = [re.compile(p, re.IGNORECASE) for p in MASTERY_PATTERNS]
    _difficulty_compiled = [re.compile(p, re.IGNORECASE) for p in DIFFICULTY_PATTERNS]
    _beginner_compiled = [re.compile(p, re.IGNORECASE) for p in BEGINNER_PATTERNS]

    @classmethod
    def detect_intent(cls, text: str) -> SignalType:
        """Detect user intent signal from message text.

        Returns:
            "mastery" - user indicates understanding
            "difficulty" - user indicates confusion
            "beginner_question" - user asks basic concept question
            None - no clear signal detected
        """
        if not text or not text.strip():
            return None

        text = text.strip()

        # Check difficulty first (higher priority - user needs help)
        for pattern in cls._difficulty_compiled:
            if pattern.search(text):
                return "difficulty"

        # Check mastery
        for pattern in cls._mastery_compiled:
            if pattern.search(text):
                return "mastery"

        # Check beginner questions
        for pattern in cls._beginner_compiled:
            if pattern.search(text):
                return "beginner_question"

        return None


# Prompt injection templates
SIGNAL_PROMPTS = {
    "mastery": (
        "【系统提示】检测到用户明确表示'理解了/学会了'。"
        "请务必调用 update_user_profile 工具，将当前讨论的核心概念/话题标记为 mastered_topic。"
        "这对个性化学习体验至关重要。"
    ),
    "difficulty": (
        "【系统提示】检测到用户表示'没看懂/有困难'。"
        "请务必调用 update_user_profile 工具，将当前话题标记为 difficult_topic，"
        "并尝试用更简单、更具体的方式重新解释。"
    ),
    "beginner_question": (
        "【系统提示】检测到用户在询问基础概念问题。"
        "请调用 update_user_profile 工具，将该话题的 expertise 标记为 beginner，"
        "并用通俗易懂的语言解释。"
    ),
}


def get_signal_injection(text: str) -> dict[str, str] | None:
    """Get the system message to inject based on detected signal.

    Returns:
        A dict with role="system" and content=injection_prompt, or None if no signal.
    """
    signal = SignalDetector.detect_intent(text)
    if signal and signal in SIGNAL_PROMPTS:
        return {"role": "system", "content": SIGNAL_PROMPTS[signal]}
    return None
