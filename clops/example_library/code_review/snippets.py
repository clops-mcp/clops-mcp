"""Reusable snippets for code review prompts."""

from clops import Snippet


severity_guidelines = Snippet(
    id="severity_guidelines",
    role="severity",
    content="""
Severity levels for code review findings:

- **Critical**: Security vulnerabilities, data loss risk, crashes in production path.
  Requires immediate fix before merge.
- **High**: Bugs that will affect users, broken functionality, missing error handling
  on external boundaries. Should block merge.
- **Medium**: Code quality issues, potential edge case bugs, suboptimal patterns.
  Should be addressed but may not block.
- **Low**: Style issues, minor inefficiencies, suggestions for improvement.
  Nice to have but optional.
""".strip(),
)


confidence_guidelines = Snippet(
    id="confidence_guidelines",
    role="confidence",
    content="""
Confidence levels for findings:

- **High**: Clear violation of established patterns or security best practices.
  The issue is unambiguous given the code visible.
- **Medium**: Likely an issue but depends on context not fully visible
  (e.g., how callers use this function, runtime environment).
- **Low**: Possible issue that warrants investigation but may be intentional
  or mitigated elsewhere.
""".strip(),
)


false_positive_patterns = Snippet(
    id="false_positive_patterns",
    role="validation",
    content="""
Common false positive patterns to filter out during validation:

- Flagging eval()/exec() when input is from trusted source (build scripts, config)
- SQL injection warnings when using parameterized queries correctly
- XSS warnings when output is already escaped by framework
- Hardcoded secrets that are actually example/test values
- Race conditions in single-threaded contexts
- Null checks where type system guarantees non-null
""".strip(),
)
