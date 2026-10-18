from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.org import Org
from app.models.org_member import OrgMember
from app.models.response import Response
from app.models.user import User
from app.routes.auth import get_current_user
from app.schemas.tenant import ChartPoint, StatsRequest, StatsResponse

router = APIRouter(prefix="/stats", tags=["stats"])

RANGE_DAYS = {
    "last_7_days": 7,
    "last_30_days": 30,
    "last_90_days": 90,
    "last_year": 365,
}

# The Philippines is UTC+8 with no daylight saving, so a fixed offset is enough
# and avoids needing the tzdata package on Windows.
LOCAL_OFFSET = timedelta(hours=8)


def granularity_for(range_key: str) -> str:
    """Bucket size for the chart: keeps the number of points readable."""
    if range_key == "all_time":
        return "month"
    if range_key == "last_year":
        return "week"
    return "day"


def bucket_floor(dt: datetime, granularity: str) -> datetime:
    dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    if granularity == "week":
        return dt - timedelta(days=dt.weekday())  # weeks start on Monday
    if granularity == "month":
        return dt.replace(day=1)
    return dt


def bucket_next(dt: datetime, granularity: str) -> datetime:
    if granularity == "week":
        return dt + timedelta(days=7)
    if granularity == "month":
        if dt.month == 12:
            return dt.replace(year=dt.year + 1, month=1)
        return dt.replace(month=dt.month + 1)
    return dt + timedelta(days=1)


def range_start(range_key: str) -> datetime | None:
    days = RANGE_DAYS.get(range_key)
    if days is None:  # "all_time"
        return None
    # naive UTC, to match datetime.utcnow() in the model
    return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)


@router.post("", response_model=StatsResponse)  # final URL: POST /stats
async def get_stats(
    body: StatsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # --- access control ---
    org = await db.scalar(select(Org).where(Org.id == body.org_id))
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found"
        )

    org_member = await db.scalar(
        select(OrgMember).where(
            OrgMember.org_id == body.org_id,
            OrgMember.user_id == current_user.id,
        )
    )
    # Deny only if the user is neither the creator nor a member
    if org.creator_id != current_user.id and not org_member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this organization",
        )

    # --- shared filter for the selected range ---
    conditions = [Response.org_id == body.org_id]
    start = range_start(body.range)
    if start is not None:
        conditions.append(Response.created_at >= start)

    # --- aggregates, computed by the database ---
    inquiry_count = (
        await db.scalar(select(func.count()).select_from(Response).where(*conditions))
        or 0
    )

    average_response_time = float(
        await db.scalar(select(func.avg(Response.latency_ms)).where(*conditions))
        or 0.0
    )

    # Only rated answers count: satisfied is NULL until someone rates it
    rated = (
        await db.scalar(
            select(func.count())
            .select_from(Response)
            .where(*conditions, Response.satisfied.is_not(None))
        )
        or 0
    )
    liked = (
        await db.scalar(
            select(func.count())
            .select_from(Response)
            .where(*conditions, Response.satisfied.is_(True))
        )
        or 0
    )
    satisfaction_rate = round(liked / rated * 100, 1) if rated else 0.0  # percent

    # --- top-10 lists, counted in Python from only the columns we need ---
    chunk_rows = await db.execute(
        select(Response.accessed_chunks, Response.created_at).where(*conditions)
    )
    chunk_counts: Counter[str] = Counter()
    chunk_last_accessed: dict[str, datetime] = {}
    for titles, created_at in chunk_rows:
        for title in titles or []:
            chunk_counts[title] += 1
            if title not in chunk_last_accessed or created_at > chunk_last_accessed[title]:
                chunk_last_accessed[title] = created_at

    # Needs a `query` text column on Response; returns {} until you add it
    inquiry_counts: Counter[str] = Counter()
    query_col = getattr(Response, "query", None)
    if query_col is not None:
        query_rows = await db.scalars(select(query_col).where(*conditions))
        for text in query_rows:
            normalized = (text or "").strip()
            if normalized:
                inquiry_counts[normalized.lower()] += 1

    top_chunks = dict(chunk_counts.most_common(10))

    # --- chart: responses per day/week/month, gaps filled with zeros ---
    granularity = granularity_for(body.range)
    # Inline literals (not bind parameters): Postgres treats the same expression
    # with different parameters as different, which breaks GROUP BY under asyncpg.
    # `granularity` only ever comes from granularity_for(), never from user input.
    bucket = func.date_trunc(
        literal_column(f"'{granularity}'"),
        Response.created_at + literal_column("interval '8 hours'"),  # = LOCAL_OFFSET
    )
    chart_rows = (
        await db.execute(
            select(bucket, func.count())
            .where(*conditions)
            .group_by(literal_column("1"))
            .order_by(literal_column("1"))
        )
    ).all()
    bucket_counts = {row[0].date(): row[1] for row in chart_rows}

    chart_data: list[ChartPoint] = []
    if bucket_counts:
        if start is not None:
            first = bucket_floor(start + LOCAL_OFFSET, granularity)
        else:  # all_time: begin at the first bucket that has data
            first = bucket_floor(
                datetime.combine(min(bucket_counts), datetime.min.time()), granularity
            )
        now_local = datetime.now(timezone.utc).replace(tzinfo=None) + LOCAL_OFFSET
        last = bucket_floor(now_local, granularity)

        current = first
        while current <= last:
            chart_data.append(
                ChartPoint(
                    date=current.date().isoformat(),
                    count=bucket_counts.get(current.date(), 0),
                )
            )
            current = bucket_next(current, granularity)

    return StatsResponse(
        inquiry_count=inquiry_count,
        satisfaction_rate=satisfaction_rate,
        average_response_time=average_response_time,
        top_10_inquiries=dict(inquiry_counts.most_common(10)),
        top_10_chunks=top_chunks,
        chart_data=chart_data,
        top_10_chunks_access_time={
            title: accessed_at.replace(tzinfo=timezone.utc)
            for title, accessed_at in sorted(
                chunk_last_accessed.items(), key=lambda item: item[1], reverse=True
            )[:10]
        },
    )