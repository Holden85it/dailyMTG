import csv

# set the name of the CSV file
file_name = "portfolioHistory.csv"

# ask for the offsetting amount
new_purchase = int(input("Enter the offsetting amount: "))

# read the CSV file and add the offsetting amount to each value
with open(file_name, 'r') as csv_file:
    reader = csv.reader(csv_file)
    rows = [row for index, row in enumerate(reader) if index != 0] # skip the first row
    for row in rows:
        row[1] = str(int(row[1]) + new_purchase)

# write the updated values back to the CSV file
with open(file_name, 'w', newline='') as csv_file:
    writer = csv.writer(csv_file)
    writer.writerow(['Date', 'Value']) # write the headers
    writer.writerows(rows)
