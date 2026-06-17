from clops import Concept


class RawArticle(Concept):
    description = (
        "A long article text that may exceed comfortable context limits. "
        "Pass the full raw text."
    )


class ArticleSummary(Concept):
    description = (
        "A condensed summary of the key points from a long article. "
        "Two to three sentences capturing the main ideas."
    )


class BriefingNote(Concept):
    description = (
        "A short executive briefing that includes a summary of the article "
        "and a one-sentence recommendation on whether to read the full text."
    )
