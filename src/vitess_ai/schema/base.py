from pydantic import BaseModel
from typing import Literal


class FillingStage(BaseModel):
    """
    This is the model to store the information about the parameters filling process, either it is processing or complete.
    Always use this tool to structure your response to the user.
    """
    stage: Literal["processing", "complete"]
