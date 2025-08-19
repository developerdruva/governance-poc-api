from pydantic import BaseModel
from typing import List, Optional

class JiraInput(BaseModel):
    project_key: str
    board_id: Optional[str] = None
    assignees: List[str]
    sprint_id: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
