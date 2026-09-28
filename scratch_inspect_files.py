import pandas as pd
import os

files = [
    'scratch/Iqra_dataset - Madinah_dataset.csv',
    'scratch/Iqra_dataset - GB_Iqra (1).csv',
    'scratch/Iqra_dataset - Campaigns_Madinah.csv',
    'scratch/Iqra_dataset - Campaign_gb.csv',
    'Sheets/Iqra_dataset - Code_breakdowns.csv'
]

for fn in files:
    full_path = os.path.join('/home/ubuntu/Python_Visualization', fn)
    if os.path.exists(full_path):
        try:
            df = pd.read_csv(full_path, nrows=5)
            print(f"=== {fn} ===")
            print("File size:", os.path.getsize(full_path), "bytes")
            print("Columns:", list(df.columns))
            print(df.head(1).to_dict(orient='records'))
            print()
        except Exception as e:
            print(f"Error reading {fn}: {e}")
