from search_service import search_incidents

results = search_incidents(
    query="payroll failure",
    severity="Critical"
)

for point in results:
    print(point.payload)