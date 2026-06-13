from typing import Optional


def retrain_model(timeframe: Optional[str] = None, force: bool = False) -> dict:
    if not force:
        from app.ml.evaluate import detect_drift
        drift = detect_drift()
        if drift["recommendation"] == "OK":
            return {"status": "skipped", "reason": "Model OK", "drift": drift}
    from app.ml.train import train_model
    from app.ml.predict import reload_model
    result = train_model(timeframe=timeframe, force=force)
    if result.get("status") == "success":
        reload_model(timeframe)
        from app.ml.evaluate import evaluate_recent
        result["post_eval"] = evaluate_recent(days=30)
    return result
