from __future__ import annotations

from lib.core.settings import Settings
from lib.domain.adapters.linkedin.linkedin_adapter import LinkedInAdapter
from lib.domain.models.job_model import Job


class ExtractLinkedInProfileTask:
    def __init__(self, settings: Settings) -> None:
        self.adapter = LinkedInAdapter(settings)

    def run(self, job: Job) -> dict:
        return self.adapter.extract_profile_basic(job.payload_json)
