from dataclasses import dataclass

@dataclass
class ModelConfig:
    max_depth: int = 5
    n_estimators: int = 500
    learning_rate: float = 0.03
    subsample: float = 0.8
    colsample_bytree: float = 0.7
    reg_alpha: float = 2.0
    reg_lambda: float = 3.0
    min_child_weight: int = 5
    gamma: float = 0.1
    scale_pos_weight: float = 1.0
    eval_metric: str = "logloss"
    early_stopping_rounds: int = 50
    random_state: int = 42

@dataclass
class TrainConfig:
    min_samples: int = 200
    n_cv_splits: int = 5
    walk_forward_window: int = 200
    walk_forward_step: int = 50
    min_auc: float = 0.55
    max_overfit_gap: float = 0.08
    model_dir: str = "app/ml/models"
    model_prefix: str = "xgb_signal"

MODEL_CONFIG = ModelConfig()
TRAIN_CONFIG = TrainConfig()
