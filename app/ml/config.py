from dataclasses import dataclass

@dataclass
class ModelConfig:
    max_depth:             int   = 4
    n_estimators:          int   = 200
    learning_rate:         float = 0.05
    subsample:             float = 0.8
    colsample_bytree:      float = 0.8
    reg_alpha:             float = 0.1
    reg_lambda:            float = 1.0
    min_child_weight:      int   = 20
    gamma:                 float = 0.0
    eval_metric:           str   = "auc"
    early_stopping_rounds: int   = 50
    random_state:          int   = 42

@dataclass
class TrainConfig:
    model_dir:       str   = "models"
    model_prefix:    str   = "xgb"
    n_cv_splits:     int   = 5
    min_samples:     int   = 300
    min_auc:         float = 0.54
    max_overfit_gap: float = 0.08
    holdout_ratio:   float = 0.20

MODEL_CONFIG = ModelConfig()
TRAIN_CONFIG = TrainConfig()