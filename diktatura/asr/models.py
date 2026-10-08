"""Diktatūra — Whisper modelio krovimas vienoje vietoje (atskiras procesas ARBA nuolatinis ASR serveris).

get_model(vardas, compute, gijos) — tokį parašą gauna ASR moduliai (`run(argv, get_model)`), todėl serveris gali
paduoti jau įkrautą modelį iš savo talpyklos, o tiesioginis paleidimas — krauti iš naujo.
"""
from diktatura import paths


def load(name: str, compute: str = "int8", threads: int = 6):
    from faster_whisper import WhisperModel
    paths.MODELS.mkdir(parents=True, exist_ok=True)
    return WhisperModel(paths.model_path(name), device="cpu", compute_type=compute, cpu_threads=threads,
                        download_root=str(paths.MODELS))
