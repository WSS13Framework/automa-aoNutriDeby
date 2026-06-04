"""gamification_router.py — Ligas e rankings NutriDeby."""
from __future__ import annotations

import logging
import random
from uuid import UUID
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from psycopg.rows import dict_row

from nutrideby.api.deps import get_settings
from nutrideby.config import Settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/gamification", tags=["gamification"])

LEAGUE_THRESHOLDS = [(0, "Bronze"), (100, "Prata"), (300, "Ouro"), (600, "Platina"), (1000, "Diamante")]

FICTITIOUS_NAMES = [
    "Ana S.", "Carlos M.", "Beatriz L.", "Diego F.", "Fernanda R.",
    "Gabriel N.", "Helena C.", "Igor T.", "Juliana P.", "Lucas O.",
    "Mariana K.", "Nicolas V.", "Olivia B.", "Pedro A.", "Rafaela D.",
    "Sergio E.", "Tatiane W.", "Ugo X.", "Vanessa Y.", "Wagner Z.",
]


@router.get("/league/{patient_id}")
def get_league(
    patient_id: UUID,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT display_name, deby_level, deby_xp, current_streak, "
                "longest_streak, league_name, league_points FROM patients WHERE id = %s",
                (patient_id,),
            )
            patient = cur.fetchone()

    if not patient:
        raise HTTPException(status_code=404, detail="Paciente não encontrado")

    my_points = patient["league_points"] or 0
    my_name = ((patient["display_name"] or "Você").split()[0])

    rng = random.Random(patient_id + str(patient["league_name"]))
    sample = rng.sample(FICTITIOUS_NAMES, min(9, len(FICTITIOUS_NAMES)))
    competitors = [{"name": name, "points": rng.randint(max(0, my_points - 50), my_points + 50)} for name in sample]
    competitors.append({"name": f"{my_name} (você)", "points": my_points})
    competitors.sort(key=lambda x: x["points"], reverse=True)
    my_rank = next(i + 1 for i, c in enumerate(competitors) if "(você)" in c["name"])

    return {
        "league_name": patient["league_name"] or "Bronze",
        "league_points": my_points,
        "deby_level": patient["deby_level"] or 1,
        "deby_xp": patient["deby_xp"] or 0,
        "current_streak": patient["current_streak"] or 0,
        "longest_streak": patient["longest_streak"] or 0,
        "my_rank": my_rank,
        "ranking": competitors[:10],
    }
