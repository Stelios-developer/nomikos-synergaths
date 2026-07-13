from fastapi import APIRouter

from services.evaluator import get_aggregate

router = APIRouter()


@router.get("/evaluation")
async def evaluation():
    return get_aggregate()
