"""Reset house data - remove test-generated maintenance records."""
import json

HOUSES_FILE = "app/data/houses.json"

with open(HOUSES_FILE, "r", encoding="utf-8") as f:
    houses = json.load(f)

# Reset house 1302's maintenance records
for h in houses:
    if h["houseId"] == "1302":
        h["maintenanceRecords"] = []
        print(f"Reset {h['houseId']} maintenance records")

with open(HOUSES_FILE, "w", encoding="utf-8") as f:
    json.dump(houses, f, ensure_ascii=False, indent=2)

print("Done")
