from clops import Op
from smoke_11_subroutine.concepts import RawArticle, ArticleSummary, BriefingNote


class SummarizeArticle(Op):
    """Standalone summarization Op — used as a subroutine by PrepareBriefing."""

    Input = RawArticle
    Output = ArticleSummary
    Intent = (
        "Read the article text and produce a two-to-three sentence summary "
        "capturing the main ideas. Focus on what happened, why it matters, "
        "and what the implications are. Do not editorialize."
    )
    Meta = (
        "Exists as a reusable summarization capability. Designed to be "
        "called as a subroutine by Ops that need to condense large text "
        "before doing further analysis. Kept as a separate Op so it gets "
        "clean context — the caller's task doesn't pollute the summarization."
    )


class PrepareBriefing(Op):
    """Entry point: produces a briefing note, using SummarizeArticle as a capability."""

    Input = RawArticle
    Output = BriefingNote
    Intent = (
        "Produce an executive briefing note for this article. The briefing "
        "should include a summary of the article and a one-sentence "
        "recommendation on whether the reader should read the full text.\n\n"
        "You have a SummarizeArticle capability available. Use it to "
        "generate the summary rather than summarizing the article yourself — "
        "it runs in a separate context optimized for summarization."
    )
    Meta = (
        "Tests the subroutine dispatch pattern. PrepareBriefing delegates "
        "summarization to SummarizeArticle via call_tool, then uses the "
        "result to compose the briefing. Validates: (1) the agent sees the "
        "subroutine in its capabilities, (2) invokes it via call_tool, "
        "(3) gets re-dispatched with the result, (4) uses the result to "
        "produce its final output."
    )
    Tools = [SummarizeArticle]
    entry = True
