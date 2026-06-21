from fastapi import APIRouter
router = APIRouter()

@router.get("/ml/status")
async def ml_status():
    from app.ml.predict import _engine
    from app.ml.feature_registry import get_feature_count, FEATURE_VERSION
    from app.db.session import SessionLocal
    from app.db.models import Signal
    with SessionLocal() as db:
        total = db.query(Signal).filter(Signal.status.in_(["WIN","LOSS"])).count()
    return {"model_loaded": _engine._get_model() is not None,
            "feature_count": get_feature_count(),
            "feature_version": FEATURE_VERSION,
            "total_training_samples": total}

@router.get("/ml/evaluate")
async def ml_evaluate(days: int = 30):
    try:
        from app.ml.evaluate import evaluate_recent
    except ImportError:
        return {
            "status": "unavailable",
            "enabled": False,
            "reason": "legacy_ml_evaluate_missing",
            "days": days,
        }
    return evaluate_recent(days=days)

@router.get("/ml/models")
async def list_models():
    import os, json
    model_dir = "app/ml/models"
    if not os.path.exists(model_dir): return {"models": []}
    models = []
    for f in os.listdir(model_dir):
        if f.endswith(".pkl") and not f.endswith("_latest.pkl"):
            path = os.path.join(model_dir, f)
            meta_path = path.replace(".pkl", "_meta.json")
            meta = {}
            if os.path.exists(meta_path):
                with open(meta_path) as fp: meta = json.load(fp)
            models.append({"filename": f, "size_kb": os.path.getsize(path)//1024,
                           "created": meta.get("created_at"), "version": meta.get("version"),
                           "feature_version": meta.get("feature_version"),
                           "timeframe": meta.get("timeframe")})
    models.sort(key=lambda x: x.get("created") or "", reverse=True)
    return {"models": models}
