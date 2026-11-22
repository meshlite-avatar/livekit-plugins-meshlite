"""Tell which lip model fits what the agent says.

The face's lips are computed in the visitor's browser by a small speech model
trained for one language. The MeshLite web SDK has one model each for English,
French and Mandarin Chinese. This is the same rule the SDK applies to the
subtitles of its own managed voice, so both paths switch at the same moment.
"""

from __future__ import annotations

import re
import unicodedata

MESHLITE_LANGUAGES = ("en", "fr", "zh-CN")
"""Language codes the MeshLite web SDK has a lip model for."""

_FRENCH_WORDS = frozenset(
    "le la les des du de un une et est sont je tu il elle nous vous ils elles ce cette ces "
    "que qui ne pas pour dans avec sur au aux mais ou donc tres bien oui non merci bonjour "
    "c'est j'ai".split()
)
_ENGLISH_WORDS = frozenset(
    "the an and is are was were i you he she we they it this that these to of in for with "
    "not but or so very well yes thanks hello what how can will".split()
)
_HAN = re.compile("[㐀-鿿]")
_ACCENTS = re.compile("[éèêàâùûçôîïë]", re.IGNORECASE)
_WORDS = re.compile("[a-z']+")


def spoken_language_of(text: str) -> str | None:
    """Return the lip-model code of the language a text is written in, if it is clear.

    Args:
        text: What the agent said in one reply.

    Returns:
        ``"zh-CN"``, ``"fr"`` or ``"en"``, or ``None`` while the text is too short or
        mixed to tell (fewer than four telling words, or no two-to-one majority).

    Examples:
        >>> spoken_language_of("Bonjour, je suis content de vous aider.")
        'fr'
        >>> spoken_language_of("Hello, I am happy to help you with this.")
        'en'
    """
    han = len(_HAN.findall(text))
    letters = sum(1 for char in text if char.isalpha())
    if han >= 4 and han > letters * 0.3:
        return "zh-CN"
    french = len(_ACCENTS.findall(text)) * 0.5
    english = 0
    plain = "".join(
        char
        for char in unicodedata.normalize("NFD", text.lower())
        if not unicodedata.combining(char)
    )
    for word in _WORDS.findall(plain):
        if word in _FRENCH_WORDS:
            french += 1
        elif word in _ENGLISH_WORDS:
            english += 1
    if french + english < 4:
        return None
    if french >= 2 * english:
        return "fr"
    if english >= 2 * french:
        return "en"
    return None
