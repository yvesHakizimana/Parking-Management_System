import redis
from datetime import datetime

r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)


def format_entry_display(entry_data):
    """Format entry data for better display"""
    if not entry_data:
        return "No data"

    plate = entry_data.get('plate_number', 'Unknown')
    entry_time = entry_data.get('entry_timestamp', 'Unknown')
    payment_status = "Paid" if entry_data.get('payment_status') == '1' else "Unpaid"
    exit_status = "Exited" if entry_data.get('exit_status') == '1' else "Inside"
    charge = entry_data.get('charge_amount', 'Not calculated')
    payment_time = entry_data.get('payment_timestamp', 'Not paid')
    exit_time = entry_data.get('exit_timestamp', 'Not exited')

    status = f"{payment_status}, {exit_status}"

    return f"""
    Plate: {plate}
    Entry: {entry_time}
    Status: {status}
    Charge: {charge} RWF
    Payment: {payment_time}
    Exit: {exit_time}
    ---"""


def get_car_status(plate_number):
    """Get comprehensive status of a car"""
    entry_ids = r.smembers(f"entries:{plate_number}")
    if not entry_ids:
        return "No entries found"

    status_info = []
    for entry_id in sorted(entry_ids, key=int):
        entry_data = r.hgetall(f"entry:{entry_id}")
        payment_status = entry_data.get('payment_status', '0')
        exit_status = entry_data.get('exit_status', '0')

        # Determine current status
        if payment_status == '0':
            current_status = "INSIDE - PAYMENT PENDING"
        elif payment_status == '1' and exit_status == '0':
            current_status = "INSIDE - PAID, READY TO EXIT"
        elif payment_status == '1' and exit_status == '1':
            current_status = "COMPLETED - EXITED"
        else:
            current_status = "UNKNOWN STATUS"

        status_info.append(f"Entry ID {entry_id}: {current_status}")

    return "\n".join(status_info)


def get_system_statistics():
    """Get comprehensive system statistics"""
    stats = {}

    # Total entries
    entry_keys = r.keys("entry:*")
    stats['total_entries'] = len(entry_keys)

    # Cars currently inside
    inside_count = 0
    unpaid_count = 0
    paid_not_exited = 0
    completed_exits = 0

    for key in entry_keys:
        entry_data = r.hgetall(key)
        payment_status = entry_data.get('payment_status', '0')
        exit_status = entry_data.get('exit_status', '0')

        if payment_status == '0':
            unpaid_count += 1
            inside_count += 1
        elif payment_status == '1' and exit_status == '0':
            paid_not_exited += 1
            inside_count += 1
        elif payment_status == '1' and exit_status == '1':
            completed_exits += 1

    stats['cars_inside'] = inside_count
    stats['unpaid_entries'] = unpaid_count
    stats['paid_not_exited'] = paid_not_exited
    stats['completed_exits'] = completed_exits

    # Total revenue (from paid entries)
    total_revenue = 0
    for key in entry_keys:
        entry_data = r.hgetall(key)
        if entry_data.get('payment_status') == '1':
            charge = entry_data.get('charge_amount', '0')
            try:
                total_revenue += float(charge)
            except (ValueError, TypeError):
                pass

    stats['total_revenue'] = total_revenue

    return stats


def show_dashboard():
    while True:
        print("\n" + "=" * 50)
        print("    PARKING MANAGEMENT DASHBOARD")
        print("=" * 50)
        print("1. View all entries")
        print("2. Search by plate number")
        print("3. List cars currently inside")
        print("4. List unpaid entries")
        print("5. View payment history")
        print("6. View system logs")
        print("7. System statistics")
        print("8. Exit")
        print("=" * 50)

        choice = input("Select an option (1-8): ").strip()

        if choice == "1":
            print("\n📋 ALL ENTRIES:")
            entries = r.keys("entry:*")
            if not entries:
                print("No entries found.")
            else:
                # Sort entries by ID
                sorted_entries = sorted(entries, key=lambda x: int(x.split(':')[1]))
                for entry_key in sorted_entries:
                    entry_data = r.hgetall(entry_key)
                    print(format_entry_display(entry_data))

        elif choice == "2":
            plate_number = input("Enter plate number (e.g., ABC123D): ").strip().upper()
            if not plate_number:
                print("❌ Invalid plate number")
                continue

            print(f"\n🔍 SEARCH RESULTS FOR: {plate_number}")
            entry_ids = r.smembers(f"entries:{plate_number}")
            if not entry_ids:
                print("No entries found for this plate number.")
            else:
                for entry_id in sorted(entry_ids, key=int):
                    entry_data = r.hgetall(f"entry:{entry_id}")
                    print(format_entry_display(entry_data))

                print(f"\n📊 CURRENT STATUS:")
                print(get_car_status(plate_number))

        elif choice == "3":
            print("\n🚗 CARS CURRENTLY INSIDE:")
            entries = r.keys("entry:*")
            inside_cars = []

            for entry_key in entries:
                entry_data = r.hgetall(entry_key)
                payment_status = entry_data.get('payment_status', '0')
                exit_status = entry_data.get('exit_status', '0')

                # Car is inside if unpaid OR paid but not exited
                if payment_status == '0' or (payment_status == '1' and exit_status != '1'):
                    inside_cars.append(entry_data)

            if not inside_cars:
                print("No cars currently inside.")
            else:
                for car in inside_cars:
                    print(format_entry_display(car))

        elif choice == "4":
            print("\n💰 UNPAID ENTRIES:")
            entries = r.keys("entry:*")
            unpaid_entries = []

            for entry_key in entries:
                entry_data = r.hgetall(entry_key)
                if entry_data.get('payment_status', '0') == '0':
                    unpaid_entries.append(entry_data)

            if not unpaid_entries:
                print("No unpaid entries found.")
            else:
                for entry in unpaid_entries:
                    print(format_entry_display(entry))

        elif choice == "5":
            print("\n💳 PAYMENT HISTORY:")
            entries = r.keys("entry:*")
            paid_entries = []

            for entry_key in entries:
                entry_data = r.hgetall(entry_key)
                if entry_data.get('payment_status', '0') == '1':
                    paid_entries.append(entry_data)

            if not paid_entries:
                print("No payment history found.")
            else:
                total_revenue = 0
                for entry in paid_entries:
                    print(format_entry_display(entry))
                    try:
                        charge = float(entry.get('charge_amount', '0'))
                        total_revenue += charge
                    except (ValueError, TypeError):
                        pass

                print(f"\n💰 TOTAL REVENUE: {total_revenue} RWF")

        elif choice == "6":
            print("\n📝 SYSTEM LOGS:")
            logs = r.lrange("logs", 0, -1)
            if not logs:
                print("No logs found.")
            else:
                # Show latest 20 logs
                recent_logs = logs[-20:] if len(logs) > 20 else logs
                for log in reversed(recent_logs):
                    print(f"  {log}")

                if len(logs) > 20:
                    print(f"\n... and {len(logs) - 20} older entries")

        elif choice == "7":
            print("\n📊 SYSTEM STATISTICS:")
            stats = get_system_statistics()

            print(f"🚗 Total Entries: {stats['total_entries']}")
            print(f"🏠 Cars Currently Inside: {stats['cars_inside']}")
            print(f"❌ Unpaid Entries: {stats['unpaid_entries']}")
            print(f"✅ Paid (Not Exited): {stats['paid_not_exited']}")
            print(f"🚪 Completed Exits: {stats['completed_exits']}")
            print(f"💰 Total Revenue: {stats['total_revenue']} RWF")

            # Additional useful statistics
            if stats['total_entries'] > 0:
                payment_rate = (stats['total_entries'] - stats['unpaid_entries']) / stats['total_entries'] * 100
                print(f"📈 Payment Rate: {payment_rate:.1f}%")

            if stats['cars_inside'] > 0:
                print(f"\n⚠️  ATTENTION: {stats['unpaid_entries']} cars need to pay before exiting")

        elif choice == "8":
            print("\n👋 Goodbye! Exiting dashboard...")
            break

        else:
            print("❌ Invalid choice. Please select 1-8.")

        # Pause before showing menu again
        input("\nPress Enter to continue...")


def search_by_plate(plate_number):
    """Standalone function to search for a specific plate"""
    plate_number = plate_number.upper().strip()
    print(f"\n🔍 SEARCHING FOR: {plate_number}")

    entry_ids = r.smembers(f"entries:{plate_number}")
    if not entry_ids:
        print("❌ No entries found for this plate number.")
        return

    print(f"✅ Found {len(entry_ids)} entries:")
    for entry_id in sorted(entry_ids, key=int):
        entry_data = r.hgetall(f"entry:{entry_id}")
        print(format_entry_display(entry_data))

    print(f"\n📊 CURRENT STATUS:")
    print(get_car_status(plate_number))


def quick_stats():
    """Quick statistics function"""
    stats = get_system_statistics()
    print("\n📊 QUICK STATS:")
    print(
        f"Cars Inside: {stats['cars_inside']} | Unpaid: {stats['unpaid_entries']} | Revenue: {stats['total_revenue']} RWF")


if __name__ == "__main__":
    try:
        show_dashboard()
    except KeyboardInterrupt:
        print("\n\n👋 Dashboard closed by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")