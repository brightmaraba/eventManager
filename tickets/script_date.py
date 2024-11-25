import pandas as pd

# Load the CSV file
df = pd.read_csv('latest.csv')

# Convert 'Created date (UTC)' to datetime and remove time
df['Created date (UTC)'] = pd.to_datetime(df['Created date (UTC)']).dt.date

# Save the updated DataFrame back to a CSV file
df.to_csv('latest_updated.csv', index=False)