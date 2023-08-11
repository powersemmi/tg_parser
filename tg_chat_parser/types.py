from typing import Annotated

from pydantic import conint

LimitedInt = Annotated[int, conint(le=200)]
