from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    jira_domain: str
    jira_email: str
    jira_api_token: str
    openai_api_key: str

    class Config:
        env_file = ".env.local"

settings = Settings()