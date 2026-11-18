from .core import api
from .routers import breakdown, exercise, meta, raw, records, reference, series, summary, yearly

api.add_router("", meta.router, tags=["meta"])
api.add_router("", reference.router, tags=["reference"])
api.add_router("", summary.router, tags=["summary"])
api.add_router("", series.router, tags=["series"])
api.add_router("", breakdown.router, tags=["breakdown"])
api.add_router("", exercise.router, tags=["exercise"])
api.add_router("", records.router, tags=["records"])
api.add_router("", yearly.router, tags=["yearly"])
api.add_router("", raw.router, tags=["raw"])
