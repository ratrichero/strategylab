from app.ml.train import train_model

result = train_model()

print("\n=== RESULT ===")
print("Status:", result["status"])
if result["status"] == "success":
    print("AUC:", result["holdout"]["auc"])
    print("Threshold:", result["recommended_threshold"])
    print("Train size:", result["train_size"])