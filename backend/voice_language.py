"""Keep a call's language stable through uncertain and short utterances."""

import math
import re
from dataclasses import dataclass

from Agent.languages import VOICE_LANGUAGES


@dataclass
class VoiceLanguage:
    current: str = "en-IN"
    established: bool = False
    candidate: str | None = None
    confirmations: int = 0

    def observe(self, text, detected, confidence=None):
        if not text.strip():
            return self.current
        # An explicit request overrides acoustic language detection: an English
        # sentence can ask Scout to continue in Punjabi.
        requested = re.search(
            r"\b(?:speak|talk|reply|respond|answer|continue)(?:\s+to me)?\s+in\s+"
            r"(" + "|".join(VOICE_LANGUAGES.values()) + r")\b",
            text,
            re.IGNORECASE,
        )
        native_requests = {
            "pa-IN": r"ਪੰਜਾਬੀ (?:ਵਿੱਚ|ਚ) (?:ਬੋਲੋ|ਗੱਲ ਕਰੋ|ਜਵਾਬ ਦਿਓ)",
            "hi-IN": r"हिंदी में (?:बोलो|बोलिए|बात करो|जवाब दो)",
        }
        explicit = next(
            (code for code, name in VOICE_LANGUAGES.items()
             if requested and name.lower() == requested[1].lower()),
            None,
        ) or next(
            (code for code, pattern in native_requests.items() if re.search(pattern, text)),
            None,
        )
        if explicit:
            self.current, self.established = explicit, True
            self.candidate, self.confirmations = None, 0
            return self.current

        detected = "od-IN" if detected == "or-IN" else detected
        reliable = confidence is None or (
            isinstance(confidence, (int, float))
            and math.isfinite(confidence)
            and 0.8 <= confidence <= 1.0
        )
        if detected not in VOICE_LANGUAGES or not reliable:
            self.candidate, self.confirmations = None, 0
            return self.current
        if not self.established:
            self.current, self.established = detected, True
        elif detected == self.current:
            self.candidate, self.confirmations = None, 0
        elif len(text.split()) >= 3 and sum(c.isalpha() for c in text) >= 12:
            # Two substantive, reliable turns in the new language prevent a
            # single code-mixed phrase from changing the conversation.
            self.confirmations = self.confirmations + 1 if self.candidate == detected else 1
            self.candidate = detected
            if self.confirmations >= 2:
                self.current = detected
                self.candidate, self.confirmations = None, 0
        else:
            self.candidate, self.confirmations = None, 0
        return self.current
