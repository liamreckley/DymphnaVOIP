from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from ..database import get_db
from ..models import RoutingRule
from ..schemas import RoutingRuleOut, RoutingRuleIn
from ..auth import require_admin, CurrentUser

router = APIRouter(prefix='/voip/admin', tags=['admin'])


@router.get('/routing-rules', response_model=list[RoutingRuleOut])
async def list_routing_rules(
    db: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(require_admin),
):
    result = await db.execute(select(RoutingRule).order_by(RoutingRule.priority))
    return result.scalars().all()


@router.post('/routing-rules', response_model=RoutingRuleOut, status_code=201)
async def create_routing_rule(
    body: RoutingRuleIn,
    db: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(require_admin),
):
    rule = RoutingRule(**body.model_dump())
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.patch('/routing-rules/{rule_id}', response_model=RoutingRuleOut)
async def update_routing_rule(
    rule_id: str,
    body: RoutingRuleIn,
    db: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(require_admin),
):
    result = await db.execute(select(RoutingRule).where(RoutingRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(404, 'Rule not found')
    for k, v in body.model_dump().items():
        setattr(rule, k, v)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.delete('/routing-rules/{rule_id}', status_code=204)
async def delete_routing_rule(
    rule_id: str,
    db: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(require_admin),
):
    await db.execute(delete(RoutingRule).where(RoutingRule.id == rule_id))
    await db.commit()
