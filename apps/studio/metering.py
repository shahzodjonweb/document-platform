"""Shared quote/settlement arithmetic for structured generation tariffs."""
import math


def generation_credits(feature,source_pages,questions,output_credits,tariff):
    source=math.ceil(source_pages/5)*tariff['source_ingestion_credits_per_started_5_pages']
    if feature=='study.flashcards':items=math.ceil(questions/10)*tariff['flashcard_credits_per_started_10_cards']
    else:items=math.ceil(questions/5)*tariff['quiz_credits_per_started_5_questions']
    base=tariff['qa_base_credits'] if feature=='study.pdf_qa' else 0
    return source+items+base+output_credits
