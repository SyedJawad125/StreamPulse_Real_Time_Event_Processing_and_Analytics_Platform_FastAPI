# # app.py
# from fastapi import FastAPI
# import joblib
# import pandas as pd

# app = FastAPI()
# model = joblib.load("house_price_model.pkl")

# @app.post("/predict")
# def predict(data: dict):
#     df = pd.DataFrame([data])
#     prediction = model.predict(df)[0]
#     return {"predicted_price": round(prediction, 2)}



from fastapi import APIRouter, HTTPException
import joblib
import pandas as pd
from pathlib import Path

router = APIRouter(
    prefix="/api/house-price",
    tags=["Machine Learning"]
)

# Get absolute path to model
model_path = Path(__file__).parent.parent / "models" / "house_price_model.pkl"

try:
    model = joblib.load(model_path)
    print(f"✅ Model loaded successfully from {model_path}")
except Exception as e:
    model = None
    print(f"⚠️ Model loading failed: {str(e)}")
    print(f"Expected model at: {model_path}")

@router.post("/predict")
async def predict_house_price(data: dict):
    if model is None:
        raise HTTPException(
            status_code=503,
            detail="Model not loaded. Please: 1) Run 'python app/models/house_price_model.py', 2) Verify the .pkl file exists, 3) Check console for loading errors"
        )
    
    try:
        # Convert input to DataFrame
        required_features = ["size_sqft", "bedrooms", "bathrooms", "location", "age_years"]
        df = pd.DataFrame([data])
        
        # Validate input
        if not all(feature in df.columns for feature in required_features):
            missing = [f for f in required_features if f not in df.columns]
            raise HTTPException(
                status_code=400,
                detail=f"Missing required features: {missing}"
            )
        
        # Make prediction
        prediction = model.predict(df)[0]
        return {
            "predicted_price": round(prediction, 2),
            "currency": "USD",
            "features_used": data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))