from dataclasses import dataclass
from datetime import date
from dataclasses import field



@dataclass
class GenerationSettings:

    research_mode: str = "auto"

    as_of_date: date = field(default_factory=date.today)

    min_queries: int = 2
    max_queries: int = 3

    min_results: int = 2
    max_results: int = 3

    min_sections: int = 2
    max_sections: int = 3

    min_bullets: int = 2
    max_bullets: int = 3

    min_words: int = 50
    max_words: int = 100

    min_images: int = 1
    max_images: int = 1