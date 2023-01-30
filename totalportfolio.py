import csv
import pandas as pd
import os
import datetime
import requests

api_key = "738beaa5-ec04-4767-8a84-5509e5afb6da"
api_endpoint = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"

# Set the request headers
headers = {
    "X-CMC_PRO_API_KEY": api_key
}

# Set the currencies and currencies to convert to
currencies = ["BTC", "ETH", "ADA", "DOGE", "ATOM", "DOT", "LTC", "XLM", "XRP", "XMR",  "BCH", "MATIC", "SOL"]
convert_to = ["GBP"]

# Set the request parameters
params = {
  "symbol": ",".join(currencies),
  "convert": ",".join(convert_to)
}

# Send the request to the API endpoint
response = requests.get(api_endpoint, params=params, headers=headers)

# Parse the response JSON
response_data = response.json()

# Create a list to store the rows of the CSV file
rows = []

# Loop through each currency and each currency to convert to
for currency in currencies:
  for convert in convert_to:
    # Get the price of the currency in the specified currency
    price = response_data["data"][currency]["quote"][convert]["price"]

    # Add a new row to the list with the currency, currency to convert to, and price
    rows.append([currency, convert, price])

# Open the CSV file for writing, overwriting any existing file
with open("currentprices.csv", "w", newline="") as csvfile:
  # Create a CSV writer
  writer = csv.writer(csvfile)

  # Write the header row
  writer.writerow(["Currency", "Convert To", "Price"])

  # Write the rows with the prices
  writer.writerows(rows)

# Read the contents of the currentprices.csv and quantities.csv files
# into separate dataframes using pandas
current_prices_df = pd.read_csv("currentprices.csv")
quantities_df = pd.read_csv("quantities.csv")

# Loop through the rows of the quantities dataframe and calculate the
# total value of each currency in your portfolio
current_value = 0
for index, row in quantities_df.iterrows():
    currency = row["Currency"]
    quantity = row["Quantity"]
    # Look up the current price of the currency in the current_prices dataframe
    # but only pick up the price if the "Convert To" column is "GBP"
    price = current_prices_df[(current_prices_df["Currency"] == currency) & (current_prices_df["Convert To"] == "GBP")]["Price"].values[0]
    # Calculate the total value of the currency in your portfolio
    value = price * quantity
    current_value += value

# Print the total value of your portfolio
print("Total value of portfolio: ", int(round(current_value,0)))

def load_csv(filename):
    if os.path.exists(filename):
        with open(filename, "r") as file:
            reader = csv.DictReader(file)
            return list(reader)
    else:
        return []

def calculate_pnl(history, current_value):
    previous_value = float(history[-1]["Value"])
    difference = current_value - previous_value
    if difference > 0:
        return "Profit: {}".format(int(round(difference,0)))
    else:
        return "Loss: {}".format(int(round(difference,0)))

def calculate_weekly_pnl(history, current_value):
        # Filter the history list to include only those dictionaries with dates from the past week
        one_week_ago = today - datetime.timedelta(weeks=1)
        filtered_history = [entry for entry in history if entry["Date"] == one_week_ago.strftime("%d-%b-%Y")]

        # Calculate the weekly PnL using the filtered history list and the current value
        weekly_pnl = calculate_pnl(filtered_history, current_value)
        return f"Weekly PnL: {weekly_pnl}"

def calculate_monthly_pnl(history, current_value):
        # Filter the history list to include only those dictionaries with dates from the past week
        one_month_ago = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(days=-1)
        filtered_history = [entry for entry in history if entry["Date"] == one_month_ago.strftime("%d-%b-%Y")]

        # Calculate the weekly PnL using the filtered history list and the current value
        month_pnl = calculate_pnl(filtered_history, current_value)
        return f"Monthly PnL: {month_pnl}"


def append_to_csv(filename, data, new_data):
    with open(filename, "a") as file:
        fieldnames = data[0].keys()
        writer = csv.DictWriter(file, fieldnames=fieldnames, lineterminator="\n")
        writer.writerow(new_data)
        file.close()

# Get the current working directory and construct the full path to the CSV file
cwd = os.getcwd()
filename = os.path.join(cwd, "portfolioHistory.csv")

# Load the data from the CSV file
data = load_csv(filename)

# Get the current date and format it using the same format as the dates in the CSV file
current_date = datetime.datetime.now().strftime("%d-%b-%Y")

# Calculate the profit and loss
pnl = calculate_pnl(data, current_value)

today = datetime.datetime.today()
day_of_week = today.weekday()

if day_of_week == 4:
    week_pnl = calculate_weekly_pnl(data, current_value)
    pnl += "\n" + week_pnl
print(pnl)

next_month = today.month + 1 if today.month < 12 else 1
next_year = today.year + 1 if next_month == 1 else today.year
last_day_current_month = today.replace(year = next_year, month=next_month, day=1, hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(days=-1)

if today.date() == last_day_current_month.date():
    monthly_pnl = calculate_monthly_pnl(data, current_value)
    pnl += "\n" + monthly_pnl
print(pnl)


# Append the current value to the CSV file
new_data = {"Date": current_date, "Value": int(round(current_value,0))}
append_to_csv(filename, data, new_data)


# Set the Pushbullet API endpoint and your API key
ENDPOINT = "https://api.pushbullet.com/v2/pushes"
API_KEY = "o.52oPsw0YJky0iG8Xwksnk7VR32SDx1yy"

# Set the parameters for the API request
params = {
    "type": "note",
    "title": "DailyPnl",
    "body": pnl
}

# Set the headers for the API request
headers = {
    "Access-Token": API_KEY,
    "Content-Type": "application/json"
}

# Make the API request
response = requests.post(ENDPOINT, json=params, headers=headers)

# Parse the response data
data = response.json()


