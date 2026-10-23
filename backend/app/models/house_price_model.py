import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LinearRegression
import joblib
from pathlib import Path
import os

def train_and_save_model():
    # Get absolute path to the dataset
    dataset_path = Path(__file__).parent.parent / "datasets" / "train.csv"
    
    # Load dataset
    df = pd.read_csv(dataset_path)
    
    # Choose features and target
    features = ["size_sqft", "bedrooms", "bathrooms", "location", "age_years"]
    X = df[features]
    y = df["price"]
    
    # Train/test split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )
    
    # Train model
    model = LinearRegression()
    model.fit(X_train, y_train)
    
    # Ensure model directory exists
    model_dir = Path(__file__).parent
    model_dir.mkdir(exist_ok=True)
    
    # Save model
    model_path = model_dir / "house_price_model.pkl"
    joblib.dump(model, model_path)
    print(f"✅ Model successfully saved to: {model_path}")
    
    return model

if __name__ == "__main__":
    train_and_save_model()



# import pandas as pd
# from sklearn.model_selection import train_test_split
# from sklearn.linear_model import LinearRegression
# from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
# import joblib
# from pathlib import Path

# def train_and_save_model():
#     # Get absolute path to the dataset
#     dataset_path = Path(__file__).parent.parent / "datasets" / "train.csv"
    
#     # Load dataset
#     df = pd.read_csv(dataset_path)
    
#     # Choose features and target
#     features = ["size_sqft", "bedrooms", "bathrooms", "location", "age_years"]
#     X = df[features]
#     y = df["price"]
    
#     # Train/test split
#     X_train, X_test, y_train, y_test = train_test_split(
#         X, y, test_size=0.2, random_state=42
#     )
    
#     # Train model
#     model = LinearRegression()
#     model.fit(X_train, y_train)
    
#     # Test model
#     y_pred = model.predict(X_test)
    
#     # Calculate metrics
#     mae = mean_absolute_error(y_test, y_pred)
#     mse = mean_squared_error(y_test, y_pred)
#     rmse = mean_squared_error(y_test, y_pred, squared=False)
#     r2 = r2_score(y_test, y_pred)
    
#     # Print evaluation results
#     print("\n📊 Model Evaluation Results:")
#     print(f"MAE: ${mae:,.2f}")
#     print(f"MSE: ${mse:,.2f}")
#     print(f"RMSE: ${rmse:,.2f}")
#     print(f"R² Score: {r2:.4f}")
    
#     # Print sample predictions vs actual
#     print("\n🔍 Sample Predictions vs Actual:")
#     sample_results = pd.DataFrame({
#         'Actual': y_test[:5],
#         'Predicted': y_pred[:5],
#         'Difference': y_test[:5] - y_pred[:5]
#     })
#     print(sample_results.to_string(index=False))
    
#     # Save model
#     model_dir = Path(__file__).parent
#     model_dir.mkdir(exist_ok=True)
#     model_path = model_dir / "house_price_model.pkl"
#     joblib.dump(model, model_path)
#     print(f"\n✅ Model successfully saved to: {model_path}")
    
#     return model

# if __name__ == "__main__":
#     train_and_save_model()