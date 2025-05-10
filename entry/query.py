import redis

r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)


def show_dashboard():
    while True:
        print("\n=== Parking Management Dashboard ===")
        print("1. View all entries")
        print("2. Search by plate number")
        print("3. List unpaid entries")
        print("4. View logs")
        print("5. Exit")

        choice = input("Select an option: ")

        if choice == "1":
            entries = r.keys("entry:*")
            for entry in entries:
                print(r.hgetall(entry))

        elif choice == "2":
            plate = input("Enter plate number (e.g., ABC123D): ").strip().upper()
            entry_ids = r.smembers(f"entries:{plate}")
            if not entry_ids:
                print("No entries found.")
            for entry_id in entry_ids:
                print(r.hgetall(f"entry:{entry_id}"))

        elif choice == "3":
            unpaid = [e for e in r.keys("entry:*") if r.hget(e, "payment_status") == "0"]
            print(f"Unpaid entries ({len(unpaid)}):")
            for entry in unpaid:
                print(r.hgetall(entry))

        elif choice == "4":
            logs = r.lrange("logs", 0, -1)
            for log in logs:
                print(log)

        elif choice == "5":
            break


show_dashboard()
