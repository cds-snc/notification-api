import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    API_HOST_NAME = os.environ.get("API_HOST_NAME")
    API_KEY = os.environ.get("API_KEY")
    EMAIL_TO = os.environ.get("EMAIL_TO", "success@simulator.amazonses.com")
    BULK_EMAIL_TEMPLATE = os.environ.get("BULK_EMAIL_TEMPLATE")
    NORMAL_EMAIL_TEMPLATE = os.environ.get("NORMAL_EMAIL_TEMPLATE")
    PRIORITY_EMAIL_TEMPLATE = os.environ.get("PRIORITY_EMAIL_TEMPLATE")
    JOB_SIZE = int(os.environ.get("JOB_SIZE", "10"))

    @classmethod
    def validate(cls):
        for x in ["API_KEY", "API_HOST_NAME", "EMAIL_TO", "JOB_SIZE"]:
            assert getattr(cls, x), f"Need {x}"
        
       
Config.validate()
