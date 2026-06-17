from clops import Op
from smoke_01_echo.concepts import Greeting


class Echo(Op):
    Input = Greeting
    Output = Greeting
    Intent = (
        "Echo the user's greeting back to them, prefixed with the literal text 'echo: '. "
        "Do nothing else. Do not interpret, expand, or rephrase the greeting."
    )
    Meta = (
        "Simplest possible Op — validates the basic dispatch/complete round trip. "
        "No tools, no composition, just echo the input."
    )
    entry = True
