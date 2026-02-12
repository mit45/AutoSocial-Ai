import random


def get_trending_topics():
    sample = [
        "AI tools 2026",
        "Productivity hacks",
        "Motivation quotes",
        "Weird facts",
        "Finance tips",
    ]
    return random.sample(sample, 3)
